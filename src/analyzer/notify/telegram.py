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


_FREE_TELEGRAM_LIMIT = 5


async def send_verdicts_tiered(verdicts: list[tuple[str, str]]) -> None:
    """Send the evening verdict batch with tier-based filtering.

    Each element of `verdicts` is (symbol, formatted_telegram_text).
    Pro subscribers (linked account + active subscription) receive all verdicts.
    Free subscribers receive the first FREE_LIMIT verdicts plus a paywall note.
    """
    from analyzer.users.store import get_pro_chat_ids

    subscribers = sub_store.get_confirmed_chat_ids()
    if not subscribers:
        return

    pro_ids = get_pro_chat_ids()
    bot = _get_bot()

    app_url = os.getenv("APP_URL", "https://yourapp.com")
    paywall_text = (
        f"🔒 <b>+{len(verdicts) - _FREE_TELEGRAM_LIMIT} more stocks for Pro subscribers</b>\n\n"
        f"Upgrade at <a href='{app_url}/subscribe'>{app_url}/subscribe</a> "
        f"to receive all {len(verdicts)} verdicts and morning follow-ups."
    )

    for chat_id in subscribers:
        is_pro = chat_id in pro_ids
        texts_to_send = (
            [t for _, t in verdicts] if is_pro else [t for _, t in verdicts[:_FREE_TELEGRAM_LIMIT]]
        )

        if not is_pro and len(verdicts) > _FREE_TELEGRAM_LIMIT:
            texts_to_send.append(paywall_text)

        for text in texts_to_send:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML" if text == paywall_text else ParseMode.MARKDOWN,
                )
                sub_store.record_delivery_success(chat_id)
                log.info("telegram_sent", chat_id=chat_id)
            except Exception as e:
                log.error("telegram_send_failed", chat_id=chat_id, error=str(e))
                sub_store.record_delivery_failure(chat_id)


async def send_morning_notes_pro(notes: list[str]) -> None:
    """Send morning notes only to Pro Telegram subscribers (linked + active subscription)."""
    from analyzer.users.store import get_pro_chat_ids

    subscribers = sub_store.get_confirmed_chat_ids()
    if not subscribers:
        return

    pro_ids = get_pro_chat_ids()
    pro_subscribers = [c for c in subscribers if c in pro_ids]
    if not pro_subscribers:
        return

    bot = _get_bot()
    for text in notes:
        for chat_id in pro_subscribers:
            try:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)
                sub_store.record_delivery_success(chat_id)
                log.info("telegram_morning_sent", chat_id=chat_id)
            except Exception as e:
                log.error("telegram_morning_send_failed", chat_id=chat_id, error=str(e))
                sub_store.record_delivery_failure(chat_id)


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
        app_url = os.getenv("APP_URL", "https://indian-stock-analyzer-five.vercel.app")
        code = sub_store.subscribe(chat_id, username=username)
        await _reply(
            chat_id,
            f"Welcome to Indian Stock Analyzer! 📊\n\n"
            f"Your verification code is: <b>{code}</b>\n\n"
            f"Reply /verify {code} to confirm.\n"
            f"Code expires in 10 minutes.\n\n"
            f"Free tier: 5 stock picks/day\n"
            f"⭐ Pro: all picks + morning follow-ups → "
            f"<a href='{app_url}/subscribe'>{app_url}/subscribe</a>\n\n"
            f"<i>Have a web account? Use /link &lt;code&gt; from your Account page — "
            f"subscribes and links in one step.</i>",
        )
        log.info("telegram_subscribe_initiated", chat_id=chat_id)

    elif command == "/verify":
        if not args:
            await _reply(chat_id, "Usage: /verify &lt;6-digit code&gt;")
            return

        app_url = os.getenv("APP_URL", "https://indian-stock-analyzer-five.vercel.app")
        success, reason = sub_store.verify(chat_id, args[0])
        if success:
            await _reply(
                chat_id,
                f"✅ <b>Subscribed!</b> You'll receive 5 stock picks every evening.\n\n"
                f"⭐ Upgrade to Pro for all picks + morning follow-ups\n"
                f"<a href='{app_url}/subscribe'>{app_url}/subscribe</a>\n\n"
                f"Use /unsubscribe to stop at any time.",
            )
            log.info("telegram_verified", chat_id=chat_id)
        else:
            messages = {
                "not_found": "No pending subscription. Send /subscribe to start.",
                "already_confirmed": "You're already subscribed! ✅",
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

    elif command == "/link":
        if not args:
            await _reply(
                chat_id,
                "Usage: /link &lt;6-digit code&gt;\n\nGet your code at Account settings on the website.",
            )
            return

        from analyzer.users.linking import consume_link_code
        from analyzer.users.store import link_telegram

        user_id = consume_link_code(args[0])
        if not user_id:
            await _reply(
                chat_id,
                "❌ Invalid or expired code.\n\n"
                "Go to Account settings on the website to generate a new code.",
            )
            log.info("telegram_link_failed_bad_code", chat_id=chat_id)
            return

        from analyzer.users.store import get_user

        link_telegram(user_id, chat_id, username)
        newly_subscribed = sub_store.ensure_confirmed(chat_id, username)
        app_url = os.getenv("APP_URL", "https://indian-stock-analyzer-five.vercel.app")

        user_record = get_user(user_id) or {}
        is_pro = user_record.get("subscription_status") == "active"

        if is_pro:
            verb = "Linked and subscribed!" if newly_subscribed else "Web account linked!"
            await _reply(
                chat_id,
                f"✅ <b>{verb}</b>\n\n"
                f"You're on Pro — you'll receive all stock picks + morning follow-ups every day 🎉",
            )
        else:
            verb = "Linked and subscribed!" if newly_subscribed else "Web account linked!"
            await _reply(
                chat_id,
                f"✅ <b>{verb}</b>\n\n"
                f"You're on the free tier — you'll receive 5 picks/day on Telegram.\n\n"
                f"⭐ Upgrade to Pro to unlock:\n"
                f"• All picks (not just 5)\n"
                f"• Morning follow-up notes\n"
                f"<a href='{app_url}/subscribe'>{app_url}/subscribe</a>",
            )
        log.info(
            "telegram_linked_via_code",
            chat_id=chat_id,
            user_id=user_id,
            is_pro=is_pro,
            newly_subscribed=newly_subscribed,
        )

    elif command == "/unlink":
        from analyzer.users.store import get_user_by_chat_id, unlink_telegram

        user = get_user_by_chat_id(chat_id)
        if not user:
            await _reply(chat_id, "This Telegram account is not linked to any web account.")
            return

        unlink_telegram(user["user_id"])
        await _reply(
            chat_id,
            "✅ Web account unlinked. You'll continue receiving free-tier picks (5 stocks/day).\n\n"
            "To stop all messages: /unsubscribe\n"
            "To re-link: /link &lt;code&gt; from your Account page",
        )
        log.info("telegram_unlinked_via_command", chat_id=chat_id)

    elif command == "/upgrade":
        app_url = os.getenv("APP_URL", "https://indian-stock-analyzer-five.vercel.app")
        await _reply(
            chat_id,
            f"⭐ <b>Upgrade to Pro</b>\n\n"
            f"Pro subscribers receive:\n"
            f"• All stock picks (not just 5)\n"
            f"• Morning follow-up notes\n"
            f"• Full web access to all picks\n\n"
            f"<a href='{app_url}/subscribe'>{app_url}/subscribe</a>",
        )

    else:
        await _reply(
            chat_id,
            "Available commands:\n\n"
            "<b>Web account users:</b>\n"
            "/link &lt;code&gt; — subscribe + link in one step (get code from Account page)\n"
            "/unlink — remove web account link (keeps free delivery)\n"
            "/upgrade — learn about Pro subscription\n\n"
            "<b>Telegram-only users:</b>\n"
            "/subscribe — sign up for free daily picks\n"
            "/verify &lt;code&gt; — confirm your subscription\n"
            "/unsubscribe — stop all messages",
        )
