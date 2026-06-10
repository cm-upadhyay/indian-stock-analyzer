"""DynamoDB-backed Telegram subscriber store.

Table: analyzer-subscribers-prod
  PK  chat_id (S)          — Telegram chat ID (always stored as string)
  status (S)               — "pending" | "confirmed" | "inactive"
  verification_code (S)    — 6-digit string, present while status=pending
  code_expires_at (N)      — Unix timestamp; code invalid after this
  attempts (N)             — verification attempts since current code was issued
  confirmed_at (S)         — ISO-8601 timestamp, set on confirm
  consecutive_failures (N) — delivery failures; 5 consecutive → inactive
  username (S)             — Telegram @username (optional, for admin display)
  created_at (S)           — ISO-8601 timestamp of first subscribe request
"""

from __future__ import annotations

import os
import random
import string
import time
from datetime import UTC, datetime
from typing import Any

import boto3
import structlog
from boto3.dynamodb.conditions import Attr

log = structlog.get_logger()

_CODE_TTL_SECS = 600  # 10 minutes to verify
_MAX_ATTEMPTS = 3
_MAX_CONSECUTIVE_FAILURES = 5


def _table() -> Any:
    name = os.getenv("SUBSCRIBERS_TABLE", "analyzer-subscribers-prod")
    return boto3.resource("dynamodb").Table(name)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _generate_code() -> str:
    return "".join(random.choices(string.digits, k=6))


# ── Write operations ──────────────────────────────────────────────────────────


def subscribe(chat_id: str, username: str = "") -> str:
    """Create or refresh a pending subscription. Returns the 6-digit verification code."""
    code = _generate_code()
    expires_at = int(time.time()) + _CODE_TTL_SECS

    _table().put_item(
        Item={
            "chat_id": str(chat_id),
            "status": "pending",
            "verification_code": code,
            "code_expires_at": expires_at,
            "attempts": 0,
            "consecutive_failures": 0,
            "username": username,
            "created_at": _now_iso(),
        }
    )
    log.info("subscriber_pending", chat_id=chat_id)
    return code


def verify(chat_id: str, code: str) -> tuple[bool, str]:
    """Attempt to verify a code. Returns (success, reason).

    Reasons on failure: "not_found", "already_confirmed", "expired", "wrong_code", "too_many_attempts"
    """
    resp = _table().get_item(Key={"chat_id": str(chat_id)})
    item = resp.get("Item")

    if not item:
        return False, "not_found"
    if item["status"] == "confirmed":
        return False, "already_confirmed"
    if item["status"] == "inactive":
        return False, "not_found"

    if int(item.get("attempts", 0)) >= _MAX_ATTEMPTS:
        return False, "too_many_attempts"

    if int(time.time()) > int(item.get("code_expires_at", 0)):
        return False, "expired"

    # Increment attempts regardless of correctness to prevent brute force
    _table().update_item(
        Key={"chat_id": str(chat_id)},
        UpdateExpression="SET attempts = attempts + :one",
        ExpressionAttributeValues={":one": 1},
    )

    if item.get("verification_code") != str(code).strip():
        return False, "wrong_code"

    _table().update_item(
        Key={"chat_id": str(chat_id)},
        UpdateExpression="SET #s = :confirmed, confirmed_at = :ts REMOVE verification_code, code_expires_at, attempts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":confirmed": "confirmed", ":ts": _now_iso()},
    )
    log.info("subscriber_confirmed", chat_id=chat_id)
    return True, "ok"


def unsubscribe(chat_id: str) -> bool:
    """Mark subscriber inactive (right-to-delete: data retained for 30 days audit trail)."""
    resp = _table().get_item(Key={"chat_id": str(chat_id)})
    if not resp.get("Item"):
        return False

    _table().update_item(
        Key={"chat_id": str(chat_id)},
        UpdateExpression="SET #s = :inactive",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":inactive": "inactive"},
    )
    log.info("subscriber_unsubscribed", chat_id=chat_id)
    return True


def record_delivery_failure(chat_id: str) -> None:
    """Increment consecutive_failures. Deactivates subscriber at threshold."""
    _table().update_item(
        Key={"chat_id": str(chat_id)},
        UpdateExpression="SET consecutive_failures = consecutive_failures + :one",
        ExpressionAttributeValues={":one": 1},
    )
    resp = _table().get_item(Key={"chat_id": str(chat_id)})
    item = resp.get("Item", {})
    if int(item.get("consecutive_failures", 0)) >= _MAX_CONSECUTIVE_FAILURES:
        _table().update_item(
            Key={"chat_id": str(chat_id)},
            UpdateExpression="SET #s = :inactive",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":inactive": "inactive"},
        )
        log.warning("subscriber_deactivated_failures", chat_id=chat_id)


def record_delivery_success(chat_id: str) -> None:
    """Reset consecutive_failures on successful delivery."""
    _table().update_item(
        Key={"chat_id": str(chat_id)},
        UpdateExpression="SET consecutive_failures = :zero",
        ExpressionAttributeValues={":zero": 0},
    )


# ── Read operations ───────────────────────────────────────────────────────────


def get_confirmed_chat_ids() -> list[str]:
    """Return all confirmed subscriber chat IDs. Falls back to env var if table unreachable."""
    try:
        resp = _table().scan(FilterExpression=Attr("status").eq("confirmed"))
        ids = [item["chat_id"] for item in resp.get("Items", [])]
        log.debug("subscribers_loaded", count=len(ids))
        return ids
    except Exception as e:
        log.error("subscribers_load_failed", error=str(e), fallback="env_var")
        # Fallback to env var so pipeline still sends if DynamoDB is down
        env_ids = os.getenv("TELEGRAM_CHAT_IDS", "")
        return [cid.strip() for cid in env_ids.split(",") if cid.strip()]


def get_all() -> list[dict[str, Any]]:
    """Return all subscriber records (admin use)."""
    resp = _table().scan()
    return resp.get("Items", [])  # type: ignore[no-any-return]


def ensure_confirmed(chat_id: str, username: str = "") -> bool:
    """Ensure chat_id has a confirmed subscriber record. Creates one if absent.

    Used when a user links their web account — they proved identity via the link
    code so no separate subscribe/verify dance is needed.

    Returns True if a new record was created, False if already confirmed.
    """
    resp = _table().get_item(Key={"chat_id": str(chat_id)})
    item = resp.get("Item")

    if item and item.get("status") == "confirmed":
        return False

    now = _now_iso()
    _table().put_item(
        Item={
            "chat_id": str(chat_id),
            "status": "confirmed",
            "confirmed_at": now,
            "consecutive_failures": 0,
            "username": username,
            "created_at": now,
        }
    )
    log.info("subscriber_auto_confirmed_via_link", chat_id=chat_id)
    return True


# ── Migration ─────────────────────────────────────────────────────────────────


def seed_from_env() -> int:
    """One-time migration: seed confirmed subscribers from TELEGRAM_CHAT_IDS env var.

    Skips chat IDs that already have a record. Returns count of new records inserted.
    """
    env_ids = os.getenv("TELEGRAM_CHAT_IDS", "")
    chat_ids = [cid.strip() for cid in env_ids.split(",") if cid.strip()]
    if not chat_ids:
        log.warning("seed_from_env_empty", hint="TELEGRAM_CHAT_IDS is not set")
        return 0

    inserted = 0
    for chat_id in chat_ids:
        resp = _table().get_item(Key={"chat_id": chat_id})
        if resp.get("Item"):
            log.info("seed_skipped_exists", chat_id=chat_id)
            continue
        _table().put_item(
            Item={
                "chat_id": chat_id,
                "status": "confirmed",
                "confirmed_at": _now_iso(),
                "consecutive_failures": 0,
                "username": "migrated",
                "created_at": _now_iso(),
            }
        )
        inserted += 1
        log.info("seed_inserted", chat_id=chat_id)

    log.info("seed_complete", inserted=inserted, total=len(chat_ids))
    return inserted
