"""Link-code generation and validation for Telegram ↔ web account linking.

Flow:
    1. Web user calls POST /api/v1/link-code  →  gets a 6-digit code (15-min TTL)
    2. User sends /link <code> to the Telegram bot
    3. Bot calls consume_link_code(code)  →  gets user_id
    4. Bot calls store.link_telegram(user_id, chat_id, chat_username)
    5. Bot replies "✅ Linked!"

Codes are stored in analyzer-link-codes-prod (hash_key = code).
TTL is enforced in application code (not a DynamoDB TTL attribute).
"""

from __future__ import annotations

import os
import random
import string
import time
from typing import Any

import structlog

log = structlog.get_logger()

_TABLE = os.getenv("LINK_CODES_TABLE", "analyzer-link-codes-prod")
_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
_TTL = 900  # 15 minutes


def _table() -> Any:
    import boto3

    return boto3.resource("dynamodb", region_name=_REGION).Table(_TABLE)


def generate_link_code(user_id: str) -> str:
    """Generate a fresh 6-digit code for user_id. Overwrites any existing code."""
    code = "".join(random.choices(string.digits, k=6))
    expires_at = int(time.time()) + _TTL
    try:
        _table().put_item(Item={"code": code, "user_id": user_id, "expires_at": expires_at})
        log.info("link_code_generated", user_id=user_id)
    except Exception as exc:
        log.error("link_code_generate_failed", user_id=user_id, error=str(exc))
        raise
    return code


def consume_link_code(code: str) -> str | None:
    """Validate the code, delete it, and return user_id. Returns None if invalid/expired."""
    try:
        resp = _table().get_item(Key={"code": code})
        item = resp.get("Item")
        if not item:
            log.info("link_code_not_found", code_prefix=code[:2])
            return None
        if int(item.get("expires_at", 0)) < int(time.time()):
            log.info("link_code_expired", code_prefix=code[:2])
            return None
        user_id = str(item["user_id"])
        # Delete code so it can't be reused
        _table().delete_item(Key={"code": code})
        log.info("link_code_consumed", user_id=user_id)
        return user_id
    except Exception as exc:
        log.warning("link_code_consume_failed", error=str(exc))
        return None
