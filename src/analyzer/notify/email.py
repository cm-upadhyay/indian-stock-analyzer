"""Email delivery via Gmail SMTP — admin list only, no verification flow.

Requires: GMAIL_SENDER and GMAIL_APP_PASSWORD env vars.
Recipients: EMAIL_RECIPIENTS (comma-separated) or same as GMAIL_SENDER.
"""

from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

log = structlog.get_logger()


def _get_recipients() -> list[str]:
    recipients = os.getenv("EMAIL_RECIPIENTS", "")
    if not recipients:
        return [os.getenv("GMAIL_SENDER", "")]
    return [r.strip() for r in recipients.split(",") if r.strip()]


def send_verdict_email(subject: str, body: str, html: bool = False) -> None:
    sender = os.getenv("GMAIL_SENDER", "")
    password = os.getenv("GMAIL_APP_PASSWORD", "")
    if not sender or not password:
        log.warning("email_not_configured")
        return

    recipients = _get_recipients()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body, "html" if html else "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipients, msg.as_string())
        log.info("email_sent", recipient_count=len(recipients))
    except Exception as e:
        log.error("email_send_failed", error=str(e))
