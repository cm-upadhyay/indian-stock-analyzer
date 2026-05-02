"""DynamoDB user store — Tasks 3.20 and 3.21.

Table: analyzer-users-prod
  PK: user_id (String) — Google OAuth `sub` claim
  Attrs: email, name, subscription_status, razorpay_subscription_id,
         subscribed_at, expires_at, updated_at

Billing: on-demand (pay-per-request). No GSI — all lookups are by user_id.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import structlog
from botocore.exceptions import ClientError

log = structlog.get_logger()

TABLE_NAME = os.getenv("USERS_TABLE", "analyzer-users-prod")
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")


def _table() -> Any:
    import boto3

    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def get_user(user_id: str) -> dict[str, Any] | None:
    """Return the user record or None if not found."""
    try:
        resp = _table().get_item(Key={"user_id": user_id})
        item: dict[str, Any] | None = resp.get("Item")
        return item
    except Exception as exc:
        log.warning("dynamo_get_user_failed", user_id=user_id, error=str(exc))
        return None


def upsert_user(user_id: str, email: str, name: str) -> None:
    """Create user record on first login; update mutable fields on subsequent logins."""
    now = _now()
    table = _table()
    try:
        table.put_item(
            Item={
                "user_id": user_id,
                "email": email,
                "name": name,
                "subscription_status": "free",
                "updated_at": now,
            },
            ConditionExpression="attribute_not_exists(user_id)",
        )
        log.info("dynamo_user_created", user_id=user_id)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            table.update_item(
                Key={"user_id": user_id},
                UpdateExpression="SET email = :e, #nm = :n, updated_at = :u",
                ExpressionAttributeNames={"#nm": "name"},
                ExpressionAttributeValues={":e": email, ":n": name, ":u": now},
            )
        else:
            log.error("dynamo_upsert_user_failed", user_id=user_id, error=str(exc))
            raise


def update_subscription(
    user_id: str,
    status: str,
    razorpay_subscription_id: str = "",
    expires_at: str = "",
) -> None:
    """Flip subscription_status — called from the Razorpay webhook handler."""
    now = _now()
    update_expr = "SET subscription_status = :s, updated_at = :u"
    attr_values: dict[str, Any] = {":s": status, ":u": now}

    if razorpay_subscription_id:
        update_expr += ", razorpay_subscription_id = :r"
        attr_values[":r"] = razorpay_subscription_id

    if expires_at:
        update_expr += ", expires_at = :e"
        attr_values[":e"] = expires_at

    if status == "active" and not expires_at:
        update_expr += ", subscribed_at = :sa"
        attr_values[":sa"] = now

    try:
        _table().update_item(
            Key={"user_id": user_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=attr_values,
        )
        log.info("dynamo_subscription_updated", user_id=user_id, status=status)
    except Exception as exc:
        log.error("dynamo_subscription_update_failed", user_id=user_id, error=str(exc))
        raise


def delete_user(user_id: str) -> None:
    """DPDP right-to-delete: hard-delete the user row."""
    try:
        _table().delete_item(Key={"user_id": user_id})
        log.info("dynamo_user_deleted", user_id=user_id)
    except Exception as exc:
        log.error("dynamo_delete_user_failed", user_id=user_id, error=str(exc))
        raise
