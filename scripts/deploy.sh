#!/usr/bin/env bash
# Deploy API Lambda + pipeline ECS image.
#
# Architecture (Phase 3B):
#   API Lambda  ← Dockerfile          (slim, --no-group local)
#   ECS Fargate ← Dockerfile.pipeline (full, includes local group with llm-guard/presidio/etc.)
#
# Run: bash scripts/deploy.sh
# Requires: AWS CLI configured, .env.prod with AWS_ACCOUNT_ID and AWS_REGION

set -euo pipefail

source .env.prod 2>/dev/null || { echo "Missing .env.prod"; exit 1; }

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="${AWS_ACCOUNT_ID}"
ECR_BASE="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
API_REPO="indian-stock-analyzer"
PIPELINE_REPO="indian-stock-analyzer-pipeline"

echo "==> Logging into ECR"
aws ecr get-login-password --region "${REGION}" | \
  docker login --username AWS --password-stdin "${ECR_BASE}"

# ── API image (Lambda) ────────────────────────────────────────────────────────
echo ""
echo "==> [1/4] Building API image (Dockerfile)"
docker build -t "${API_REPO}:latest" .

echo "==> [2/4] Pushing API image"
docker tag "${API_REPO}:latest" "${ECR_BASE}/${API_REPO}:latest"
docker push "${ECR_BASE}/${API_REPO}:latest"

echo "==> Updating API Lambda function"
# --query: the full response dumps every env var (secrets) to the terminal
aws lambda update-function-code \
  --function-name analyzer-api \
  --image-uri "${ECR_BASE}/${API_REPO}:latest" \
  --region "${REGION}" \
  --no-cli-pager \
  --query "{State: State, LastUpdateStatus: LastUpdateStatus, CodeSha256: CodeSha256}"

# ── Pipeline image (ECS Fargate) ──────────────────────────────────────────────
echo ""
echo "==> [3/4] Building pipeline image (Dockerfile.pipeline)"
echo "    (includes llm-guard, presidio, nemoguardrails, guardrails-ai — may take a few minutes)"
docker build -f Dockerfile.pipeline -t "${PIPELINE_REPO}:latest" .

echo "==> [4/4] Pushing pipeline image"
docker tag "${PIPELINE_REPO}:latest" "${ECR_BASE}/${PIPELINE_REPO}:latest"
docker push "${ECR_BASE}/${PIPELINE_REPO}:latest"

echo ""
echo "==> Pipeline image pushed. ECS tasks will use the new image on next EventBridge trigger."
echo "    (Task definitions point to :latest — no task def update needed.)"

# ── Status check ──────────────────────────────────────────────────────────────
echo ""
echo "==> Deploy complete. Verifying Lambda state..."
aws lambda get-function --function-name analyzer-api \
  --query 'Configuration.{State:State,LastModified:LastModified}' \
  --output table --region "${REGION}" --no-cli-pager
