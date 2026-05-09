#!/usr/bin/env bash
set -euo pipefail

# Run from terraform/envs/prod/
# Usage: bash import.sh
# Imports all existing prod resources into Terraform state.
# Safe to re-run — already-imported resources print a warning and are skipped.

import() {
  echo "→ importing $1"
  terraform import "$@" || echo "  ⚠ skipped (already imported or does not exist)"
}

# ECR
import module.ecr_api.aws_ecr_repository.this        indian-stock-analyzer
import module.ecr_pipeline.aws_ecr_repository.this   indian-stock-analyzer-pipeline

# S3
import module.s3_data.aws_s3_bucket.this             analyzer-data-prod

# DynamoDB
import module.dynamo_users.aws_dynamodb_table.this   analyzer-users-prod

# IAM — Lambda role + 3 policy attachments
import module.iam.aws_iam_role.this                  analyzer-lambda-role
import 'module.iam.aws_iam_role_policy_attachment.policies["arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess"]' \
       'analyzer-lambda-role/arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess'
import 'module.iam.aws_iam_role_policy_attachment.policies["arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"]' \
       'analyzer-lambda-role/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'
import 'module.iam.aws_iam_role_policy_attachment.policies["arn:aws:iam::aws:policy/AmazonS3FullAccess"]' \
       'analyzer-lambda-role/arn:aws:iam::aws:policy/AmazonS3FullAccess'

# Lambda functions
import module.lambda_api.aws_lambda_function.this      analyzer-api
import module.lambda_pipeline.aws_lambda_function.this analyzer-pipeline
import module.lambda_morning.aws_lambda_function.this  analyzer-morning

# Lambda function URL
import aws_lambda_function_url.api                   analyzer-api

# ECS cluster
import aws_ecs_cluster.main                          indian-stock-analyzer

# EventBridge schedules
import aws_scheduler_schedule.pipeline_ecs           default/analyzer-pipeline-ecs
import aws_scheduler_schedule.morning_ecs            default/analyzer-morning-ecs
import aws_scheduler_schedule.pipeline_daily         default/analyzer-pipeline-daily
import aws_scheduler_schedule.morning_daily          default/analyzer-morning-daily

# ECS IAM roles + policy attachments
import aws_iam_role.ecs_execution                    ecs-pipeline-execution-role
import 'aws_iam_role_policy_attachment.ecs_execution_policies["arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"]' \
       'ecs-pipeline-execution-role/arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy'
import 'aws_iam_role_policy_attachment.ecs_execution_policies["arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess"]' \
       'ecs-pipeline-execution-role/arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess'

import aws_iam_role.ecs_task                         ecs-pipeline-task-role
import 'aws_iam_role_policy_attachment.ecs_task_policies["arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess"]' \
       'ecs-pipeline-task-role/arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess'
import 'aws_iam_role_policy_attachment.ecs_task_policies["arn:aws:iam::aws:policy/AmazonS3FullAccess"]' \
       'ecs-pipeline-task-role/arn:aws:iam::aws:policy/AmazonS3FullAccess'

import aws_iam_role.eventbridge_ecs                  eventbridge-scheduler-ecs-role
import aws_iam_role_policy_attachment.eventbridge_ecs_policy \
       'eventbridge-scheduler-ecs-role/arn:aws:iam::aws:policy/AmazonECS_FullAccess'

# CloudWatch log groups
import aws_cloudwatch_log_group.lambda_api      /aws/lambda/analyzer-api
import aws_cloudwatch_log_group.lambda_pipeline /aws/lambda/analyzer-pipeline
import aws_cloudwatch_log_group.lambda_morning  /aws/lambda/analyzer-morning
import aws_cloudwatch_log_group.ecs_pipeline    /ecs/indian-stock-analyzer-pipeline
import aws_cloudwatch_log_group.ecs_morning     /ecs/indian-stock-analyzer-morning

# SSM parameters (17)
# for_each key = short name (e.g. "OPENAI_API_KEY"), import ID = full SSM path
for param in \
  OPENAI_API_KEY GEMINI_API_KEY TAVILY_API_KEY \
  TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_IDS ADMIN_CHAT_ID \
  GMAIL_SENDER GMAIL_APP_PASSWORD \
  LANGSMITH_API_KEY LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY \
  QDRANT_URL QDRANT_API_KEY \
  NEXTAUTH_SECRET RAZORPAY_WEBHOOK_SECRET \
  API_KEY SENTRY_DSN; do
  terraform import "aws_ssm_parameter.secrets[\"${param}\"]" \
    "/indian-stock-analyzer/prod/${param}"
done

echo ""
echo "✓ Import complete. Run 'terraform plan' to verify zero drift."
