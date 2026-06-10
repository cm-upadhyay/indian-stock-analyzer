"""Email delivery via AWS SES.

Sender must be verified in SES (domain or address).
Requires: GMAIL_SENDER env var as the From address (already verified).
Pro user emails come from DynamoDB via get_pro_emails().
"""

from __future__ import annotations

import os
from collections.abc import Callable

import structlog

log = structlog.get_logger()

REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")


def _get_admin_recipients() -> list[str]:
    """Hardcoded admin list — used for operator digest when no Pro users exist."""
    recipients = os.getenv("EMAIL_RECIPIENTS", "")
    if not recipients:
        return [os.getenv("GMAIL_SENDER", "")]
    return [r.strip() for r in recipients.split(",") if r.strip()]


def _ses_send(subject: str, body: str, recipients: list[str], html: bool = True) -> None:
    """Send via SES. Skips silently if sender not configured."""
    sender = os.getenv("GMAIL_SENDER", "")
    if not sender:
        log.warning("email_sender_not_configured")
        return
    if not recipients:
        return

    import boto3

    ses = boto3.client("ses", region_name=REGION)
    body_key = "Html" if html else "Text"
    try:
        ses.send_email(
            Source=sender,
            Destination={"ToAddresses": recipients},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {body_key: {"Data": body, "Charset": "UTF-8"}},
            },
        )
        log.info("email_sent_ses", recipient_count=len(recipients))
    except Exception as exc:
        log.error("email_send_failed", error=str(exc))
        raise


def send_verdict_email(subject: str, body: str, html: bool = False) -> None:
    """Send to admin recipient list (operator digest)."""
    _ses_send(subject, body, _get_admin_recipients(), html)


def send_verdict_email_pro(
    subject: str,
    body_fn: Callable[[str], str],
) -> None:
    """Send evening digest to all opted-in Pro users.

    body_fn receives a per-user unsubscribe URL so each email has a unique link.
    """
    from analyzer.users.store import get_pro_emails

    pro_users = get_pro_emails()
    if not pro_users:
        log.info("email_pro_no_recipients")
        return

    app_url = os.getenv("APP_URL", "")
    if not app_url:
        log.warning("app_url_not_configured_unsubscribe_links_missing")
    sent = 0
    for user in pro_users:
        unsubscribe_url = f"{app_url}/api/unsubscribe-email?token={user['unsubscribe_token']}"
        body = body_fn(unsubscribe_url)
        try:
            _ses_send(subject, body, [user["email"]])
            sent += 1
        except Exception:
            pass  # already logged inside _ses_send

    log.info("email_pro_digest_sent", sent=sent, total=len(pro_users))
