locals {
  account_id = var.account_id
  region     = var.region
  ecr_base   = "${local.account_id}.dkr.ecr.${local.region}.amazonaws.com"
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

module "dynamo_subscribers" {
  source   = "../../modules/dynamodb_table"
  name     = "analyzer-subscribers-prod"
  hash_key = "chat_id"
}

module "dynamo_hitl_checkpoints" {
  source    = "../../modules/dynamodb_table"
  name      = "analyzer-hitl-checkpoints-prod"
  hash_key  = "PK"
  range_key = "SK"
}

# ── IAM role ──────────────────────────────────────────────────────────────────

module "iam" {
  source    = "../../modules/iam"
  role_name = "analyzer-lambda-role"
  policy_arns = [
    # AmazonSSMReadOnlyAccess removed — replaced by least-privilege inline policy below
    # AmazonS3FullAccess removed — replaced by least-privilege inline policy below
    "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
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
  # AmazonSSMReadOnlyAccess removed — replaced by least-privilege inline policy below
  # AmazonS3FullAccess removed — replaced by least-privilege inline policy below
  for_each   = toset([])
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

# AmazonECS_FullAccess removed — replaced by least-privilege inline policy below

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
    "TELEGRAM_WEBHOOK_SECRET",
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

# ── IAM least-privilege policies (Tasks 4.5, 4.13) ───────────────────────────
# Replaces all AWS-managed wildcard policies:
#   AmazonSSMReadOnlyAccess → scoped to /indian-stock-analyzer/prod/*
#   AmazonS3FullAccess      → scoped to analyzer-data-prod bucket
#   AmazonECS_FullAccess    → scoped to RunTask + PassRole on project cluster/tasks

locals {
  ssm_prefix_arn = "arn:aws:ssm:${local.region}:${local.account_id}:parameter/indian-stock-analyzer/prod/*"
  ssm_path_arn   = "arn:aws:ssm:${local.region}:${local.account_id}:parameter/indian-stock-analyzer/prod"
  s3_bucket_arn  = "arn:aws:s3:::analyzer-data-prod"

  # Shared by Lambda role, ECS execution role, and ECS task role
  app_least_privilege_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SSMProjectOnly"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",        # application GetParameter calls
          "ssm:GetParameters",       # ECS native secrets injection (fetches multiple by ARN)
          "ssm:GetParametersByPath", # load_secrets_from_ssm() batch load — evaluated against path ARN (no /*)
        ]
        Resource = [local.ssm_prefix_arn, local.ssm_path_arn]
      },
      {
        Sid    = "S3ProjectBucketOnly"
        Effect = "Allow"
        Action = [
          "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
          "s3:ListBucket", "s3:GetBucketLocation",
        ]
        Resource = [local.s3_bucket_arn, "${local.s3_bucket_arn}/*"]
      },
      {
        Sid    = "DynamoDBProjectTablesOnly"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
          "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan",
          "dynamodb:BatchWriteItem", "dynamodb:BatchGetItem",
        ]
        Resource = [
          "arn:aws:dynamodb:${local.region}:${local.account_id}:table/analyzer-users-prod",
          "arn:aws:dynamodb:${local.region}:${local.account_id}:table/analyzer-subscribers-prod",
          "arn:aws:dynamodb:${local.region}:${local.account_id}:table/analyzer-hitl-checkpoints-prod",
        ]
      },
    ]
  })

  # EventBridge scheduler: only RunTask on the project cluster + PassRole
  eventbridge_least_privilege_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ECSRunTaskProjectOnly"
        Effect = "Allow"
        Action = ["ecs:RunTask"]
        Resource = [
          "arn:aws:ecs:${local.region}:${local.account_id}:task-definition/indian-stock-analyzer-pipeline:*",
          "arn:aws:ecs:${local.region}:${local.account_id}:task-definition/indian-stock-analyzer-morning:*",
        ]
        Condition = {
          ArnLike = {
            "ecs:cluster" = "arn:aws:ecs:${local.region}:${local.account_id}:cluster/indian-stock-analyzer"
          }
        }
      },
      {
        Sid    = "PassRoleToECS"
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = [
          aws_iam_role.ecs_execution.arn,
          aws_iam_role.ecs_task.arn,
        ]
        Condition = {
          StringLike = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" }
        }
      },
    ]
  })
}

resource "aws_iam_role_policy" "lambda_least_privilege" {
  name   = "app-least-privilege"
  role   = module.iam.role_name
  policy = local.app_least_privilege_policy
}

resource "aws_iam_role_policy" "ecs_execution_least_privilege" {
  name   = "app-least-privilege"
  role   = aws_iam_role.ecs_execution.name
  policy = local.app_least_privilege_policy
}

resource "aws_iam_role_policy" "ecs_task_least_privilege" {
  name   = "app-least-privilege"
  role   = aws_iam_role.ecs_task.name
  policy = local.app_least_privilege_policy
}

resource "aws_iam_role_policy" "eventbridge_ecs_least_privilege" {
  name   = "ecs-run-task-project-only"
  role   = aws_iam_role.eventbridge_ecs.name
  policy = local.eventbridge_least_privilege_policy
}

# ── GitHub Actions OIDC (Task 4.3) ───────────────────────────────────────────
# Allows GitHub Actions CI to push API images to ECR and update Lambda.
# No long-lived AWS credentials — uses short-lived OIDC tokens.

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_role" "github_actions_deploy" {
  name = "github-actions-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = data.aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          # Only allow the main branch of this repo
          "token.actions.githubusercontent.com:sub" = "repo:cm-upadhyay/indian-stock-analyzer:ref:refs/heads/main"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github_actions_deploy" {
  name = "ecr-push-lambda-update"
  role = aws_iam_role.github_actions_deploy.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ECRAuth"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = ["*"]
      },
      {
        Sid    = "ECRPushAPIImage"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
        ]
        Resource = "arn:aws:ecr:${local.region}:${local.account_id}:repository/indian-stock-analyzer"
      },
      {
        Sid      = "LambdaUpdateCode"
        Effect   = "Allow"
        Action   = ["lambda:UpdateFunctionCode", "lambda:GetFunction", "lambda:GetFunctionConfiguration"]
        Resource = "arn:aws:lambda:${local.region}:${local.account_id}:function:analyzer-api"
      },
    ]
  })
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

# ── CloudWatch alarms + SNS (Task 4.11) ──────────────────────────────────────
# All alarms → SNS → Lambda subscriber that forwards to admin Telegram.
# runbook_url tag on each alarm tells on-call what page to check.

resource "aws_sns_topic" "alerts" {
  name = "analyzer-alerts-prod"
}

# Forward SNS alerts to admin Telegram via API Lambda
# The Lambda /api/v1/admin/alert endpoint handles SNS → Telegram forwarding.
resource "aws_sns_topic_subscription" "alerts_lambda" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "https"
  # CloudFront URL is known after first apply — set this after initial deploy
  endpoint = "${module.cloudfront_api.url}/api/v1/admin/alert"

  lifecycle {
    ignore_changes = [endpoint]
  }
}

locals {
  alarm_actions = [aws_sns_topic.alerts.arn]

  lambda_functions = {
    api      = { name = "analyzer-api", log_group = "/aws/lambda/analyzer-api" }
    pipeline = { name = "analyzer-pipeline", log_group = "/aws/lambda/analyzer-pipeline" }
    morning  = { name = "analyzer-morning", log_group = "/aws/lambda/analyzer-morning" }
  }
}

# Lambda: errors ≥ 3 in 5 min
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each            = local.lambda_functions
  alarm_name          = "lambda-${each.key}-errors"
  alarm_description   = "${each.key} Lambda error count ≥ 3 in 5 min"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = each.value.name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  tags = { runbook_url = "https://github.com/cm-upadhyay/indian-stock-analyzer/wiki/runbook-lambda-errors" }
}

# Lambda: duration P95 > 25 s (API Lambda timeout is 30 s)
resource "aws_cloudwatch_metric_alarm" "lambda_duration" {
  for_each            = local.lambda_functions
  alarm_name          = "lambda-${each.key}-duration-p95"
  alarm_description   = "${each.key} Lambda P95 duration > 25 000 ms"
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"
  dimensions          = { FunctionName = each.value.name }
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 2
  threshold           = 25000
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions

  tags = { runbook_url = "https://github.com/cm-upadhyay/indian-stock-analyzer/wiki/runbook-lambda-duration" }
}

# Lambda: throttles ≥ 1 in 5 min (signals concurrency limit hit)
resource "aws_cloudwatch_metric_alarm" "lambda_throttles" {
  for_each            = local.lambda_functions
  alarm_name          = "lambda-${each.key}-throttles"
  alarm_description   = "${each.key} Lambda throttle count ≥ 1 in 5 min"
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  dimensions          = { FunctionName = each.value.name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions

  tags = { runbook_url = "https://github.com/cm-upadhyay/indian-stock-analyzer/wiki/runbook-lambda-throttles" }
}

# DynamoDB: throttled requests ≥ 5 in 5 min across all project tables
resource "aws_cloudwatch_metric_alarm" "dynamodb_throttles" {
  for_each = {
    users       = "analyzer-users-prod"
    subscribers = "analyzer-subscribers-prod"
    hitl        = "analyzer-hitl-checkpoints-prod"
  }
  alarm_name          = "dynamodb-${each.key}-throttles"
  alarm_description   = "DynamoDB ${each.value} throttled requests ≥ 5 in 5 min"
  namespace           = "AWS/DynamoDB"
  metric_name         = "ThrottledRequests"
  dimensions          = { TableName = each.value }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions

  tags = { runbook_url = "https://github.com/cm-upadhyay/indian-stock-analyzer/wiki/runbook-dynamodb-throttles" }
}

# WAF: blocked requests ≥ 50 in 5 min (anomaly / attack pattern)
resource "aws_cloudwatch_metric_alarm" "waf_blocked" {
  alarm_name        = "waf-blocked-requests"
  alarm_description = "WAF blocking ≥ 50 requests in 5 min — possible attack pattern"
  namespace         = "AWS/WAFV2"
  metric_name       = "BlockedRequests"
  dimensions = {
    WebACL = "analyzer-api-waf"
    Rule   = "ALL"
    Region = local.region
  }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 50
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions

  tags = { runbook_url = "https://github.com/cm-upadhyay/indian-stock-analyzer/wiki/runbook-waf-blocked" }
}

# ── Outputs ───────────────────────────────────────────────────────────────────

output "alerts_sns_topic_arn" {
  value       = aws_sns_topic.alerts.arn
  description = "SNS topic ARN for CloudWatch alarms — subscribe email/Telegram here"
}

output "github_actions_role_arn" {
  value       = aws_iam_role.github_actions_deploy.arn
  description = "IAM role ARN for GitHub Actions OIDC — set as AWS_DEPLOY_ROLE_ARN in GitHub secrets"
}

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
