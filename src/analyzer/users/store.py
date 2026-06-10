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


def link_telegram(user_id: str, chat_id: str, chat_username: str = "") -> None:
    """Store the Telegram chat_id on the user record (called after /link <code>)."""
    try:
        _table().update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET chat_id = :c, chat_username = :u, updated_at = :t",
            ExpressionAttributeValues={":c": chat_id, ":u": chat_username, ":t": _now()},
        )
        log.info("telegram_linked", user_id=user_id, chat_id=chat_id)
    except Exception as exc:
        log.error("telegram_link_failed", user_id=user_id, error=str(exc))
        raise


def unlink_telegram(user_id: str) -> None:
    """Remove the Telegram link from the user record."""
    try:
        _table().update_item(
            Key={"user_id": user_id},
            UpdateExpression="REMOVE chat_id, chat_username SET updated_at = :t",
            ExpressionAttributeValues={":t": _now()},
        )
        log.info("telegram_unlinked", user_id=user_id)
    except Exception as exc:
        log.error("telegram_unlink_failed", user_id=user_id, error=str(exc))
        raise


def get_user_by_chat_id(chat_id: str) -> dict[str, Any] | None:
    """Look up a user by Telegram chat_id via the GSI on that attribute."""
    import boto3
    from boto3.dynamodb.conditions import Key as DKey

    try:
        table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
        resp = table.query(
            IndexName="chat_id-index",
            KeyConditionExpression=DKey("chat_id").eq(chat_id),
            Limit=1,
        )
        items = resp.get("Items", [])
        return items[0] if items else None
    except Exception as exc:
        log.warning("dynamo_get_user_by_chat_id_failed", chat_id=chat_id, error=str(exc))
        return None


def get_pro_chat_ids() -> set[str]:
    """Return chat_ids of users with an active subscription and a linked Telegram account."""
    import boto3
    from boto3.dynamodb.conditions import Attr

    try:
        table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
        resp = table.scan(
            FilterExpression=Attr("chat_id").exists() & Attr("subscription_status").eq("active"),
            ProjectionExpression="chat_id",
        )
        return {item["chat_id"] for item in resp.get("Items", [])}
    except Exception as exc:
        log.warning("dynamo_get_pro_chat_ids_failed", error=str(exc))
        return set()


def get_pro_emails() -> list[dict[str, str]]:
    """Return email + unsubscribe token for Pro users who haven't opted out of email.

    Used by the pipeline to send the evening digest and morning notes to Pro users.
    Each dict has: email, name, user_id, unsubscribe_token.
    """
    import base64
    import hashlib
    import hmac as hmac_lib

    import boto3
    from boto3.dynamodb.conditions import Attr

    secret = os.getenv("NEXTAUTH_SECRET", "").encode()

    try:
        table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
        resp = table.scan(
            FilterExpression=Attr("subscription_status").eq("active")
            & Attr("email_opt_out").ne(True),
            ProjectionExpression="user_id, email, #nm",
            ExpressionAttributeNames={"#nm": "name"},
        )
        result = []
        for item in resp.get("Items", []):
            uid = item.get("user_id", "")
            token = base64.urlsafe_b64encode(
                hmac_lib.new(secret, uid.encode(), hashlib.sha256).digest()[:12]
            ).decode()
            result.append(
                {
                    "user_id": uid,
                    "email": item.get("email", ""),
                    "name": item.get("name", ""),
                    "unsubscribe_token": f"{uid}.{token}",
                }
            )
        return result
    except Exception as exc:
        log.warning("dynamo_get_pro_emails_failed", error=str(exc))
        return []


def set_email_opt_out(user_id: str, opt_out: bool) -> None:
    """Set or clear the email_opt_out flag on a user record."""
    try:
        if opt_out:
            _table().update_item(
                Key={"user_id": user_id},
                UpdateExpression="SET email_opt_out = :v, updated_at = :t",
                ExpressionAttributeValues={":v": True, ":t": _now()},
            )
        else:
            _table().update_item(
                Key={"user_id": user_id},
                UpdateExpression="REMOVE email_opt_out SET updated_at = :t",
                ExpressionAttributeValues={":t": _now()},
            )
        log.info("email_opt_out_set", user_id=user_id, opt_out=opt_out)
    except Exception as exc:
        log.error("email_opt_out_failed", user_id=user_id, error=str(exc))
        raise
