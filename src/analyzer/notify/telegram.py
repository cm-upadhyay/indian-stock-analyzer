"""Telegram delivery and bot command handler.

Outbound (pipeline → subscribers):
    send_verdict(), send_morning_note(), send_failure_alert()
    → reads confirmed subscriber chat IDs from DynamoDB (via subscribers module)
    → falls back to TELEGRAM_CHAT_IDS env var if DynamoDB unreachable

Inbound (user → bot → Lambda webhook):
    handle_update() processes Telegram Update objects posted to POST /api/v1/telegram/webhook
    Supported commands: /start, /subscribe, /verify <code>, /unsubscribe
"""

from __future__ import annotations

import os
from typing import Any

import structlog
from telegram import Bot
from telegram.constants import ParseMode

from analyzer.notify import subscribers as sub_store

log = structlog.get_logger()


def _get_bot() -> Bot:
    return Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])


# ── Outbound: pipeline → subscribers ─────────────────────────────────────────


async def send_message(
    text: str,
    parse_mode: str = ParseMode.MARKDOWN,
    chat_ids: list[str] | None = None,
) -> None:
    """Send text to all confirmed subscribers (or an explicit list of chat IDs)."""
    bot = _get_bot()
    recipients = chat_ids if chat_ids is not None else sub_store.get_confirmed_chat_ids()
    if not recipients:
        log.warning("no_telegram_recipients")
        return
    for chat_id in recipients:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            sub_store.record_delivery_success(chat_id)
            log.info("telegram_sent", chat_id=chat_id)
        except Exception as e:
            log.error("telegram_send_failed", chat_id=chat_id, error=str(e))
            sub_store.record_delivery_failure(chat_id)


async def send_verdict(formatted_text: str) -> None:
    await send_message(formatted_text)


async def send_morning_note(text: str) -> None:
    await send_message(text)


async def send_failure_alert(error: str) -> None:
    await send_message(
        f"⚠️ *Pipeline failure*\n```\n{error[:500]}\n```",
        chat_ids=[os.getenv("ADMIN_CHAT_ID", "")],
    )


# ── Inbound: bot command handler ──────────────────────────────────────────────


async def _reply(chat_id: str, text: str) -> None:
    """Send a plain-text reply to a single chat via direct Telegram API call."""
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
        log.info("telegram_replied", chat_id=chat_id)
    except Exception as e:
        log.error("telegram_reply_failed", chat_id=chat_id, error=str(e))


async def _answer_callback(callback_query_id: str, text: str = "") -> None:
    """Acknowledge a Telegram callback query — removes the loading spinner on the button."""
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id, "text": text},
            )
    except Exception as e:
        log.error("telegram_answer_callback_failed", error=str(e))


async def handle_update(update: dict[str, Any]) -> None:
    """Process a Telegram Update object received from the webhook.

    Handles: /start, /subscribe, /verify <code>, /unsubscribe
    Handles: HITL callback_query (hitl_approve:<thread_id>, hitl_reject:<thread_id>)
    """
    # ── HITL inline button callbacks ──────────────────────────────────────────
    if "callback_query" in update:
        query = update["callback_query"]
        callback_id = query["id"]
        caller_id = str(query["from"]["id"])
        data = query.get("data", "")
        admin_id = os.getenv("ADMIN_CHAT_ID", "")

        if not (data.startswith("hitl_approve:") or data.startswith("hitl_reject:")):
            await _answer_callback(callback_id, "Unknown action.")
            return

        if caller_id != admin_id:
            await _answer_callback(callback_id, "❌ Not authorized.")
            return

        await _answer_callback(callback_id, "Processing...")

        action, thread_id = data.split(":", 1)
        approved = action == "hitl_approve"

        from analyzer.pipeline.graph_4pm import resume_4pm

        state = resume_4pm(thread_id, approved=approved)

        if state is None:
            await _reply(caller_id, "⏱ Verdict expired or not found.")
            return

        symbol = thread_id.split("_")[0]
        if approved and state.verdict and state.stock and state.scoring:
            from datetime import date

            from analyzer.llm.formatter import format_email_html, format_telegram
            from analyzer.notify.email import send_verdict_email

            await send_verdict(
                "✅ *Late addition — approved after review:*\n\n"
                + format_telegram(
                    symbol=state.stock.symbol,
                    company_name=state.stock.company_name,
                    current_price=state.stock.current_price,
                    verdict=state.verdict,
                    scoring=state.scoring,
                )
            )
            today = date.today()
            v = state.verdict
            signal = v.signal
            subject = (
                f"Indian Stock Analyzer · {today.strftime('%d %b %Y')} · "
                f"Late addition: {symbol} {signal}"
            )
            send_verdict_email(
                subject,
                format_email_html(
                    [
                        {
                            "symbol": state.stock.symbol,
                            "company_name": state.stock.company_name,
                            "current_price": state.stock.current_price,
                            "beta": state.fund.beta if state.fund else None,
                            "scoring": state.scoring,
                            "verdict": state.verdict,
                        }
                    ],
                    today,
                ),
                html=True,
            )
            await _reply(caller_id, f"✅ <b>{symbol}</b> verdict published.")
        else:
            await _reply(caller_id, f"❌ <b>{symbol}</b> verdict rejected — dropped.")
        return

    # ── Bot commands ──────────────────────────────────────────────────────────
    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    chat_id = str(message["chat"]["id"])
    text = (message.get("text") or "").strip()
    username = message.get("from", {}).get("username", "")

    if not text.startswith("/"):
        return

    command = text.split()[0].lower().split("@")[0]  # strip bot username suffix
    args = text.split()[1:]

    if command in ("/start", "/subscribe"):
        code = sub_store.subscribe(chat_id, username=username)
        await _reply(
            chat_id,
            f"Welcome to Indian Stock Analyzer!\n\n"
            f"Your verification code is: <b>{code}</b>\n\n"
            f"Reply with /verify {code} to confirm your subscription.\n"
            f"Code expires in 10 minutes.",
        )
        log.info("telegram_subscribe_initiated", chat_id=chat_id)

    elif command == "/verify":
        if not args:
            await _reply(chat_id, "Usage: /verify &lt;6-digit code&gt;")
            return

        success, reason = sub_store.verify(chat_id, args[0])
        if success:
            await _reply(
                chat_id,
                "✅ Subscription confirmed! You'll receive stock verdicts every evening "
                "and morning follow-ups on weekdays.\n\nUse /unsubscribe to stop at any time.",
            )
            log.info("telegram_verified", chat_id=chat_id)
        else:
            messages = {
                "not_found": "No pending subscription. Send /subscribe to start.",
                "already_confirmed": "You're already subscribed!",
                "expired": "Code expired. Send /subscribe to get a new code.",
                "wrong_code": "Wrong code. Please check and try again.",
                "too_many_attempts": "Too many attempts. Send /subscribe to get a new code.",
            }
            await _reply(
                chat_id, messages.get(reason, "Verification failed. Try /subscribe again.")
            )

    elif command == "/unsubscribe":
        removed = sub_store.unsubscribe(chat_id)
        if removed:
            await _reply(
                chat_id,
                "You've been unsubscribed. You won't receive any more messages.\n\n"
                "Send /subscribe anytime to re-subscribe.",
            )
            log.info("telegram_unsubscribed", chat_id=chat_id)
        else:
            await _reply(chat_id, "You weren't subscribed. Send /subscribe to sign up.")

    else:
        await _reply(
            chat_id,
            "Available commands:\n"
            "/subscribe — subscribe to daily stock verdicts\n"
            "/verify &lt;code&gt; — verify your subscription\n"
            "/unsubscribe — stop receiving messages",
        )
