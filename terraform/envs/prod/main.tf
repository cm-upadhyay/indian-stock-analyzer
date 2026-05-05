locals {
  account_id = var.account_id
  region     = var.region
  ecr_base   = "${local.account_id}.dkr.ecr.${local.region}.amazonaws.com"
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
    "arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess",
    "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    "arn:aws:iam::aws:policy/AmazonS3FullAccess",
  ]
}

# ── Lambda API ────────────────────────────────────────────────────────────────

module "lambda_api" {
  source        = "../../modules/lambda_function"
  function_name = "analyzer-api"
  image_uri     = "${local.ecr_base}/indian-stock-analyzer:latest"
  role_arn      = module.iam.role_arn
  memory_size   = 512
  timeout       = 30
}
