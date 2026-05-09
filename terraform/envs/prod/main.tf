locals {
  account_id        = var.account_id
  region            = var.region
  ecr_base          = "${local.account_id}.dkr.ecr.${local.region}.amazonaws.com"
  # Strip https:// and trailing slash from Lambda function URL to get bare domain
  lambda_url_domain = trimsuffix(replace(aws_lambda_function_url.api.function_url, "https://", ""), "/")
}

# ── ECR repositories ──────────────────────────────────────────────────────────

module "ecr_api" {
  source = "../../modules/ecr"
  name   = "indian-stock-analyzer"
}

module "ecr_pipeline" {
  source = "../../modules/ecr"
  name   = "indian-stock-analyzer-pipeline"
}

# ── S3 data bucket ────────────────────────────────────────────────────────────

module "s3_data" {
  source = "../../modules/s3_bucket"
  bucket = "analyzer-data-prod"
}

# ── DynamoDB tables ───────────────────────────────────────────────────────────

module "dynamo_users" {
  source   = "../../modules/dynamodb_table"
  name     = "analyzer-users-prod"
  hash_key = "user_id"
}

# ── IAM role ──────────────────────────────────────────────────────────────────

module "iam" {
  source    = "../../modules/iam"
  role_name = "analyzer-lambda-role"
  policy_arns = [
    # AmazonSSMReadOnlyAccess removed — replaced by least-privilege inline policy below
    "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    "arn:aws:iam::aws:policy/AmazonS3FullAccess",
  ]
}

# ── Lambda functions ──────────────────────────────────────────────────────────

module "lambda_api" {
  source        = "../../modules/lambda_function"
  function_name = "analyzer-api"
  image_uri     = "${local.ecr_base}/indian-stock-analyzer:latest"
  role_arn      = module.iam.role_arn
  memory_size   = 512
  timeout       = 30
}

module "lambda_pipeline" {
  source        = "../../modules/lambda_function"
  function_name = "analyzer-pipeline"
  image_uri     = "${local.ecr_base}/indian-stock-analyzer-pipeline:latest"
  role_arn      = module.iam.role_arn
  memory_size   = 2048
  timeout       = 900
}

module "lambda_morning" {
  source        = "../../modules/lambda_function"
  function_name = "analyzer-morning"
  image_uri     = "${local.ecr_base}/indian-stock-analyzer-pipeline:latest"
  role_arn      = module.iam.role_arn
  memory_size   = 512
  timeout       = 300
}

# ── Lambda function URL (public, auth handled by FastAPI JWT check) ────────────

resource "aws_lambda_function_url" "api" {
  function_name      = module.lambda_api.function_name
  authorization_type = "NONE"

  lifecycle {
    ignore_changes = [cors]
  }
}

# ── ECS cluster ───────────────────────────────────────────────────────────────

resource "aws_ecs_cluster" "main" {
  name = "indian-stock-analyzer"
}

# ── ECS IAM roles ─────────────────────────────────────────────────────────────
# These roles are used by ECS task definitions (pipeline + morning tasks).
# Trust: ecs-tasks.amazonaws.com (different from Lambda role above).

resource "aws_iam_role" "ecs_execution" {
  name = "ecs-pipeline-execution-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_policies" {
  for_each = toset([
    "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
    # AmazonSSMReadOnlyAccess removed — replaced by least-privilege inline policy below
  ])
  role       = aws_iam_role.ecs_execution.name
  policy_arn = each.value
}

resource "aws_iam_role" "ecs_task" {
  name = "ecs-pipeline-task-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_policies" {
  for_each = toset([
    # AmazonSSMReadOnlyAccess removed — replaced by least-privilege inline policy below
    "arn:aws:iam::aws:policy/AmazonS3FullAccess",
  ])
  role       = aws_iam_role.ecs_task.name
  policy_arn = each.value
}

resource "aws_iam_role" "eventbridge_ecs" {
  name = "eventbridge-scheduler-ecs-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eventbridge_ecs_policy" {
  role       = aws_iam_role.eventbridge_ecs.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonECS_FullAccess"
}

# ── CloudWatch log groups ─────────────────────────────────────────────────────
# Retention set to 30 days — logs were previously kept forever (no retention).

resource "aws_cloudwatch_log_group" "lambda_api" {
  name              = "/aws/lambda/analyzer-api"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "lambda_pipeline" {
  name              = "/aws/lambda/analyzer-pipeline"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "lambda_morning" {
  name              = "/aws/lambda/analyzer-morning"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "ecs_pipeline" {
  name              = "/ecs/indian-stock-analyzer-pipeline"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "ecs_morning" {
  name              = "/ecs/indian-stock-analyzer-morning"
  retention_in_days = 30
}

# ── SSM parameters ────────────────────────────────────────────────────────────
# Secret values are managed outside Terraform (never in .tf files or state).
# ignore_changes = [value] means Terraform tracks that the param exists but
# never reads or modifies the encrypted value.

locals {
  ssm_params = [
    "OPENAI_API_KEY", "GEMINI_API_KEY", "TAVILY_API_KEY",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_IDS", "ADMIN_CHAT_ID",
    "GMAIL_SENDER", "GMAIL_APP_PASSWORD",
    "LANGSMITH_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY",
    "QDRANT_URL", "QDRANT_API_KEY",
    "NEXTAUTH_SECRET", "RAZORPAY_WEBHOOK_SECRET",
    "API_KEY", "SENTRY_DSN",
  ]
}

resource "aws_ssm_parameter" "secrets" {
  for_each = toset(local.ssm_params)
  name     = "/indian-stock-analyzer/prod/${each.value}"
  type     = "SecureString"
  value    = "managed-externally"

  lifecycle {
    ignore_changes = [value]
  }
}

# ── EventBridge schedules ─────────────────────────────────────────────────────
# Task definition ARNs change with every pipeline deploy — ignore them here.
# The deploy script (scripts/deploy.sh) updates task defs; Terraform just
# ensures the schedules exist with the right cron expression.

resource "aws_scheduler_schedule" "pipeline_ecs" {
  name                         = "analyzer-pipeline-ecs"
  schedule_expression          = "cron(30 16 ? * MON-FRI *)"
  schedule_expression_timezone = "Asia/Kolkata"
  state                        = "ENABLED"

  flexible_time_window { mode = "OFF" }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = "arn:aws:iam::${local.account_id}:role/eventbridge-scheduler-ecs-role"
    input    = "{}"

    ecs_parameters {
      task_definition_arn = "arn:aws:ecs:${local.region}:${local.account_id}:task-definition/indian-stock-analyzer-pipeline"
      launch_type         = "FARGATE"
      network_configuration {
        assign_public_ip = true
        subnets          = ["subnet-012887bb45571b03d"]
      }
    }

    retry_policy {
      maximum_event_age_in_seconds = 86400
      maximum_retry_attempts       = 185
    }
  }

  lifecycle {
    ignore_changes = [target[0].ecs_parameters[0].task_definition_arn]
  }
}

resource "aws_scheduler_schedule" "morning_ecs" {
  name                         = "analyzer-morning-ecs"
  schedule_expression          = "cron(0 8 ? * MON-FRI *)"
  schedule_expression_timezone = "Asia/Kolkata"
  state                        = "ENABLED"

  flexible_time_window { mode = "OFF" }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = "arn:aws:iam::${local.account_id}:role/eventbridge-scheduler-ecs-role"
    input    = "{}"

    ecs_parameters {
      task_definition_arn = "arn:aws:ecs:${local.region}:${local.account_id}:task-definition/indian-stock-analyzer-morning"
      launch_type         = "FARGATE"
      network_configuration {
        assign_public_ip = true
        subnets          = ["subnet-012887bb45571b03d"]
      }
    }

    retry_policy {
      maximum_event_age_in_seconds = 86400
      maximum_retry_attempts       = 185
    }
  }

  lifecycle {
    ignore_changes = [target[0].ecs_parameters[0].task_definition_arn]
  }
}

# Lambda-based fallback schedules (currently DISABLED — ECS schedules are active)
resource "aws_scheduler_schedule" "pipeline_daily" {
  name                         = "analyzer-pipeline-daily"
  schedule_expression          = "cron(30 16 ? * MON-FRI *)"
  schedule_expression_timezone = "Asia/Kolkata"
  state                        = "DISABLED"

  flexible_time_window { mode = "OFF" }

  target {
    arn      = module.lambda_pipeline.function_arn
    role_arn = "arn:aws:iam::${local.account_id}:role/service-role/eventbridge-lambda-scheduler-role"

    retry_policy {
      maximum_event_age_in_seconds = 86400
      maximum_retry_attempts       = 0
    }
  }
}

resource "aws_scheduler_schedule" "morning_daily" {
  name                         = "analyzer-morning-daily"
  schedule_expression          = "cron(0 8 ? * MON-FRI *)"
  schedule_expression_timezone = "Asia/Kolkata"
  state                        = "DISABLED"

  flexible_time_window { mode = "OFF" }

  target {
    arn      = module.lambda_morning.function_arn
    role_arn = "arn:aws:iam::${local.account_id}:role/service-role/eventbridge-lambda-scheduler-role"

    retry_policy {
      maximum_event_age_in_seconds = 86400
      maximum_retry_attempts       = 0
    }
  }
}

# ── IAM least-privilege: SSM scoped to project prefix (Task 4.5) ──────────────
# Replaces AmazonSSMReadOnlyAccess (account-wide) with a policy that only allows
# reading /indian-stock-analyzer/prod/* parameters.

locals {
  ssm_prefix_arn = "arn:aws:ssm:${local.region}:${local.account_id}:parameter/indian-stock-analyzer/prod/*"

  ssm_least_privilege_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameter", "ssm:GetParametersByPath"]
      Resource = local.ssm_prefix_arn
    }]
  })
}

resource "aws_iam_role_policy" "lambda_ssm" {
  name   = "ssm-read-project-only"
  role   = module.iam.role_name
  policy = local.ssm_least_privilege_policy
}

resource "aws_iam_role_policy" "ecs_execution_ssm" {
  name   = "ssm-read-project-only"
  role   = aws_iam_role.ecs_execution.name
  policy = local.ssm_least_privilege_policy
}

resource "aws_iam_role_policy" "ecs_task_ssm" {
  name   = "ssm-read-project-only"
  role   = aws_iam_role.ecs_task.name
  policy = local.ssm_least_privilege_policy
}

# ── WAF WebACL (Task 4.7) ─────────────────────────────────────────────────────

module "waf" {
  source = "../../modules/waf"
  name   = "analyzer-api-waf"
}

# ── CloudFront (Task 4.6) ─────────────────────────────────────────────────────

module "cloudfront_api" {
  source            = "../../modules/cloudfront"
  lambda_url_domain = local.lambda_url_domain
  web_acl_arn       = module.waf.web_acl_arn
  comment           = "Indian Stock Analyzer API"
}

# ── Outputs ───────────────────────────────────────────────────────────────────

output "cloudfront_url" {
  value       = module.cloudfront_api.url
  description = "CloudFront URL — use this as API_BASE_URL in Vercel"
}

output "cloudfront_domain" {
  value       = module.cloudfront_api.distribution_domain
  description = "Bare CloudFront domain (without https://)"
}

output "waf_arn" {
  value       = module.waf.web_acl_arn
  description = "WAF WebACL ARN"
}
