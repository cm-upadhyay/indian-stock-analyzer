"""Telegram delivery — sends verdicts and morning notes to admin subscriber list.

Subscriber chat IDs come from TELEGRAM_CHAT_IDS env var (comma-separated)
or config/subscribers.yaml. No DynamoDB yet — Phase 4.
"""

from __future__ import annotations

import os

import structlog
from telegram import Bot
from telegram.constants import ParseMode

log = structlog.get_logger()


def _get_bot() -> Bot:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    return Bot(token=token)


def _get_chat_ids() -> list[str]:
    ids = os.getenv("TELEGRAM_CHAT_IDS", "")
    return [cid.strip() for cid in ids.split(",") if cid.strip()]


async def send_message(text: str, parse_mode: str = ParseMode.MARKDOWN) -> None:
    bot = _get_bot()
    chat_ids = _get_chat_ids()
    if not chat_ids:
        log.warning("no_telegram_recipients_configured")
        return
    for chat_id in chat_ids:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            log.info("telegram_sent", chat_id=chat_id)
        except Exception as e:
            log.error("telegram_send_failed", chat_id=chat_id, error=str(e))


async def send_verdict(formatted_text: str) -> None:
    await send_message(formatted_text)


async def send_morning_note(text: str) -> None:
    await send_message(text)


async def send_failure_alert(error: str) -> None:
    await send_message(f"⚠️ *Pipeline failure*\n```\n{error[:500]}\n```")
