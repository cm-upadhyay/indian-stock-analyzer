"""Human-in-the-Loop (HITL) approver — pause high-stakes verdicts for human review.

What HITL means:
    Most verdicts are published automatically. But some are risky:
        - Low-confidence directional calls (confidence < HITL_CONFIDENCE_TRIGGER AND signal = BUY or SELL)
        - Calls where the reflection reviewer overrode the primary verdict
        - Small-cap stocks with outsized price targets (> HITL_LARGE_TARGET_UPSIDE upside)
        - Any verdict where NeMo flagged a soft policy concern

    For these, the graph PAUSES at the human_review node before publishing.
    An admin gets a Telegram message with Approve / Reject buttons.
    If approved within HITL_TIMEOUT_SECS → verdict is published.
    If rejected or timed out → verdict is dropped (not published).

How LangGraph HITL works:
    LangGraph's compile(interrupt_before=["human_review"]) stops execution
    BEFORE entering the human_review node. State is checkpointed to SQLite.
    A separate call (resume_graph) resumes execution from the checkpoint.

Limitations in Phase 3A (fixed in Phase 4):
    - SQLite checkpointer stores state in a LOCAL FILE (data/hitl.db or /tmp/hitl.db)
    - On Lambda, if the container is recycled between the interrupt and the
      Telegram callback, the state is lost and the verdict is dropped silently
    - Phase 4 replaces SQLite with DynamoDB (survives cold starts across invocations)
    - For now: HITL works perfectly on local dev; on Lambda it's best-effort

Env:
    ENABLE_HITL              — "true"/"false" (default: false — enable explicitly)
    HITL_DB_PATH             — path to SQLite file (default: data/hitl.db)
    HITL_TIMEOUT_SECS        — how long to wait for human response (default: 1800 = 30 min)
    HITL_CONFIDENCE_TRIGGER  — confidence below which HITL fires (default: 0.50)
    HITL_LARGE_TARGET_UPSIDE — upside ratio above which HITL fires for BUY (default: 0.30)
    ADMIN_CHAT_ID            — Telegram chat ID to send approval requests to
    API_BASE_URL             — base URL of the FastAPI server (default: http://localhost:8000)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import structlog

from analyzer.config import settings
from analyzer.data.models import StockVerdict

log = structlog.get_logger()

_ENABLED = settings.enable_hitl
_DB_PATH = settings.hitl_db_path
_TIMEOUT_SECS = settings.hitl_timeout_secs


# ── Trigger conditions ────────────────────────────────────────────────────────


def should_trigger_hitl(
    verdict: StockVerdict,
    reflection_overrode: bool = False,
    nemo_soft_flag: bool = False,
) -> bool:
    """Decide whether this verdict requires human approval before publishing.

    Returns True if ANY of the following conditions are met:
        1. Directional call (BUY/SELL) with confidence < HITL_CONFIDENCE_TRIGGER
        2. Reflection reviewer overrode the primary verdict
        3. Small-cap BUY with target > HITL_LARGE_TARGET_UPSIDE above entry
        4. NeMo raised a soft policy flag

    Returns False if HITL is disabled via env var.
    """
    if not _ENABLED:
        return False

    if verdict.signal in ("BUY", "SELL") and verdict.confidence < settings.hitl_confidence_trigger:
        log.info(
            "hitl_trigger_low_confidence", signal=verdict.signal, confidence=verdict.confidence
        )
        return True

    if reflection_overrode:
        log.info("hitl_trigger_reflection_override")
        return True

    if nemo_soft_flag:
        log.info("hitl_trigger_nemo_flag")
        return True

    if verdict.signal == "BUY" and verdict.entry is not None and verdict.target is not None:
        upside = (verdict.target - verdict.entry) / verdict.entry
        if upside > settings.hitl_large_target_upside:
            log.info("hitl_trigger_large_target", upside=upside)
            return True

    return False


# ── Telegram approval ─────────────────────────────────────────────────────────


def send_approval_request(thread_id: str, symbol: str, verdict: StockVerdict) -> bool:
    """Send a Telegram message asking the admin to approve or reject this verdict.

    The message includes the full verdict summary and two inline keyboard buttons:
        ✅ Approve — publishes the verdict
        ❌ Reject  — drops the verdict

    The admin must click within HITL_TIMEOUT_SECS or the verdict is dropped.

    Returns True if the Telegram message was sent successfully.
    """
    admin_chat_id = settings.admin_chat_id
    if not admin_chat_id:
        log.warning("hitl_no_admin_chat_id", hint="Set ADMIN_CHAT_ID env var")
        return False

    bot_token = settings.telegram_bot_token
    if not bot_token:
        log.warning("hitl_no_bot_token")
        return False

    try:
        import html

        import requests

        price_line = ""
        if verdict.entry:
            price_line = f"\n📍 Entry: ₹{verdict.entry:,} | Stop: ₹{verdict.stop_loss:,} | Target: ₹{verdict.target:,}"

        approve_url = f"{settings.api_base_url}/hitl/approve/{thread_id}"
        reject_url = f"{settings.api_base_url}/hitl/reject/{thread_id}"
        is_local = "localhost" in settings.api_base_url or "127.0.0.1" in settings.api_base_url

        # Telegram rejects localhost URLs in inline buttons — show them as text for local dev
        action_line = (
            f"\n✅ Approve: <code>{approve_url}</code>\n❌ Reject: <code>{reject_url}</code>"
            if is_local
            else ""
        )

        message = (
            f"⚠️ <b>HITL Review Required</b>\n\n"
            f"<b>{html.escape(symbol)}</b> — {verdict.signal} ({verdict.confidence:.0%} confidence){price_line}\n\n"
            f"<i>{html.escape(verdict.whats_happening[:200])}</i>\n\n"
            f"⚠️ <i>{html.escape(verdict.watch_out_for[:150])}</i>\n\n"
            f"Thread ID: <code>{html.escape(thread_id)}</code>\n"
            f"Expires in: {_TIMEOUT_SECS // 60} minutes"
            f"{action_line}"
        )

        keyboard = (
            None
            if is_local
            else {
                "inline_keyboard": [
                    [
                        {"text": "✅ Approve", "url": approve_url},
                        {"text": "❌ Reject", "url": reject_url},
                    ]
                ]
            }
        )

        payload: dict[str, Any] = {
            "chat_id": admin_chat_id,
            "text": message,
            "parse_mode": "HTML",
        }
        if keyboard:
            payload["reply_markup"] = keyboard

        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json=payload,
            timeout=10,
        )
        if not resp.ok:
            log.error("hitl_telegram_rejected", status=resp.status_code, body=resp.text[:500])
        resp.raise_for_status()
        log.info("hitl_approval_sent", thread_id=thread_id, symbol=symbol)
        return True

    except Exception as e:
        log.error("hitl_send_failed", thread_id=thread_id, error=str(e))
        return False


# ── SQLite checkpointer ───────────────────────────────────────────────────────


def get_checkpointer():  # type: ignore[no-untyped-def]
    """Return a LangGraph SQLite checkpointer for HITL state persistence.

    Phase 4 replaces this with DynamoDB:
        from langgraph.checkpoint.dynamodb import DynamoDBSaver
        return DynamoDBSaver(table_name="analyzer-hitl-checkpoints-prod")
    """
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        db_path = Path(_DB_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return SqliteSaver.from_conn_string(str(db_path))
    except ImportError:
        log.warning("langgraph_sqlite_not_available", hint="pip install langgraph[sqlite]")
        return None
    except Exception as e:
        log.warning("hitl_checkpointer_init_failed", error=str(e))
        return None


# ── Decision storage (simple file-based for Phase 3A) ────────────────────────

_DECISION_ROOT = Path("data/hitl_decisions")


def record_decision(thread_id: str, approved: bool) -> None:
    """Record an admin approve/reject decision. Called by the API endpoint."""
    _DECISION_ROOT.mkdir(parents=True, exist_ok=True)
    decision_file = _DECISION_ROOT / f"{thread_id}.json"
    decision_file.write_text(json.dumps({"approved": approved, "ts": time.time()}))
    log.info("hitl_decision_recorded", thread_id=thread_id, approved=approved)


def poll_for_decision(thread_id: str) -> bool | None:
    """Poll for an admin decision. Returns True=approved, False=rejected, None=pending."""
    decision_file = _DECISION_ROOT / f"{thread_id}.json"
    if not decision_file.exists():
        return None
    try:
        data = json.loads(decision_file.read_text())
        return bool(data.get("approved", False))
    except Exception:
        return None


def wait_for_decision(thread_id: str, timeout_secs: int = _TIMEOUT_SECS) -> bool:
    """Block (with polling) until admin decides or timeout. Returns True=approved.

    Used in local dev where we can afford to block the process.
    On Lambda: don't call this — use the interrupt/resume pattern instead.
    """
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        decision = poll_for_decision(thread_id)
        if decision is not None:
            return decision
        time.sleep(5)
    log.warning("hitl_timeout", thread_id=thread_id, timeout_secs=timeout_secs)
    return False
