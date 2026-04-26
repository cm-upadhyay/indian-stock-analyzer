"""Load secrets from AWS SSM Parameter Store into os.environ at Lambda cold start.

Only runs when ENVIRONMENT=production. Local dev uses .env as before.
"""

from __future__ import annotations

import os

import structlog

log = structlog.get_logger()

_PREFIX = "/indian-stock-analyzer/prod"


def load_secrets_from_ssm() -> None:
    """Pull all SecureString parameters under the project prefix into os.environ.

    Uses setdefault so explicitly-set env vars are never overridden.
    boto3 is imported lazily — local dev never touches it.
    Raises on failure so Lambda fails fast rather than starting with missing secrets.
    """
    if os.getenv("ENVIRONMENT") != "production":
        return

    try:
        import boto3  # provided by Lambda runtime; not required locally

        client = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "ap-south-1"))
        paginator = client.get_paginator("get_parameters_by_path")
        loaded = 0
        for page in paginator.paginate(Path=_PREFIX, WithDecryption=True):
            for param in page["Parameters"]:
                key = param["Name"].rsplit("/", 1)[-1]
                os.environ.setdefault(key, param["Value"])
                loaded += 1
        log.info("ssm_secrets_loaded", count=loaded, prefix=_PREFIX)
    except Exception as exc:
        log.error("ssm_load_failed", error=str(exc))
        raise
