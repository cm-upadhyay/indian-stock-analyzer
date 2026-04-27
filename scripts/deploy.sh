#!/usr/bin/env bash
# Deploy all three Lambda functions via Docker + ECR.
# Run: bash scripts/deploy.sh
# Requires: AWS CLI configured, .env.prod with ACCOUNT_ID and REGION

set -euo pipefail

source .env.prod 2>/dev/null || { echo "Missing .env.prod"; exit 1; }

REGION="${AWS_REGION:-ap-south-1}"
ACCOUNT_ID="${AWS_ACCOUNT_ID}"
ECR_REPO="indian-stock-analyzer"
IMAGE_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}"

echo "==> Building Docker image"
docker build -t "${ECR_REPO}:latest" .

echo "==> Logging into ECR"
aws ecr get-login-password --region "${REGION}" | \
  docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

echo "==> Tagging and pushing"
docker tag "${ECR_REPO}:latest" "${IMAGE_URI}:latest"
docker push "${IMAGE_URI}:latest"

echo "==> Updating Lambda functions"
for FUNCTION in analyzer-pipeline analyzer-morning analyzer-api; do
  echo "  Updating ${FUNCTION}..."
  aws lambda update-function-code \
    --function-name "${FUNCTION}" \
    --image-uri "${IMAGE_URI}:latest" \
    --region "${REGION}" \
    --no-cli-pager
done

echo "==> Deploy complete. Waiting for update to propagate..."
sleep 5
for FUNCTION in analyzer-pipeline analyzer-morning analyzer-api; do
  aws lambda get-function --function-name "${FUNCTION}" \
    --query 'Configuration.{State:State,LastModified:LastModified}' \
    --output table --region "${REGION}" --no-cli-pager
done
