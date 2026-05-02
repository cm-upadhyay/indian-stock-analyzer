"""Lambda handler entry points for the two pipeline functions.

analyzer-pipeline (4:30 PM IST EventBridge trigger):
    CMD = ["analyzer.pipeline.lambda_handlers.pipeline_handler"]

analyzer-morning (8:00 AM IST EventBridge trigger):
    CMD = ["analyzer.pipeline.lambda_handlers.morning_handler"]
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog
from dotenv import load_dotenv

from analyzer.utils.logging import configure_logging

load_dotenv()
configure_logging()
log = structlog.get_logger()

from analyzer.observability.langfuse_client import flush as flush_langfuse  # noqa: E402
from analyzer.observability.sentry_setup import flush as flush_sentry  # noqa: E402
from analyzer.observability.sentry_setup import init_sentry  # noqa: E402
from analyzer.utils.secrets import load_secrets_from_ssm  # noqa: E402

load_secrets_from_ssm()
init_sentry()


def pipeline_handler(event: dict, context: object) -> dict:  # type: ignore[type-arg]
    """4:30 PM: screener → 30 stocks → full analysis → store verdicts → notify."""
    import re
    from datetime import date

    from analyzer.flags import get_flag
    from analyzer.llm.formatter import format_email_html, format_telegram
    from analyzer.notify import telegram as tg
    from analyzer.notify.email import send_verdict_email
    from analyzer.pipeline.graph_4pm import run_4pm
    from analyzer.screener import run_screener
    from analyzer.utils.storage import AnalysisStore

    symbols_env = os.getenv("SYMBOLS", "")
    if symbols_env:
        raw_symbols = [s.strip().upper() for s in symbols_env.split(",")]
        valid_pattern = re.compile(r"^[A-Z0-9&-]{1,20}\.NS$")
        symbols = [s for s in raw_symbols if valid_pattern.match(s)]
        if len(symbols) != len(raw_symbols):
            rejected = [s for s in raw_symbols if not valid_pattern.match(s)]
            log.warning("pipeline_invalid_symbols_skipped", rejected=rejected)
    else:
        symbols = run_screener()

    log.info("pipeline_lambda_start", symbols_count=len(symbols))

    store = AnalysisStore()
    today = date.today()
    results = []
    email_stocks: list[dict[str, Any]] = []

    for symbol in symbols:
        # Idempotency: if Lambda fires twice (AWS at-least-once), skip already-processed symbols
        if store.load(today, symbol) is not None:
            log.info("already_processed_skipping", symbol=symbol, date=str(today))
            continue

        try:
            state = run_4pm(symbol)
            if state.verdict and state.stock and state.scoring:
                if get_flag("kill_switch_publish_verdicts"):
                    log.warning("kill_switch_active_skipping", symbol=symbol)
                    continue

                store.save(today, symbol, state.verdict)
                results.append({"symbol": symbol, "signal": state.verdict.signal})

                asyncio.run(
                    tg.send_verdict(
                        format_telegram(
                            symbol=state.stock.symbol,
                            company_name=state.stock.company_name,
                            current_price=state.stock.current_price,
                            verdict=state.verdict,
                            scoring=state.scoring,
                        )
                    )
                )

                email_stocks.append(
                    {
                        "symbol": state.stock.symbol,
                        "company_name": state.stock.company_name,
                        "current_price": state.stock.current_price,
                        "beta": state.fund.beta if state.fund else None,
                        "scoring": state.scoring,
                        "verdict": state.verdict,
                    }
                )
        except Exception as e:
            log.error("stock_failed", symbol=symbol, error=str(e))

    if email_stocks:
        buy = sum(1 for s in email_stocks if s["verdict"].signal == "BUY")
        hold = sum(1 for s in email_stocks if s["verdict"].signal == "HOLD")
        sell = sum(1 for s in email_stocks if s["verdict"].signal == "SELL")
        subject = (
            f"Indian Stock Analyzer · {today.strftime('%d %b %Y')} · "
            f"{buy} BUY · {hold} HOLD · {sell} SELL"
        )
        send_verdict_email(subject, format_email_html(email_stocks, today), html=True)
        log.info("pipeline_email_sent", count=len(email_stocks))

    log.info("pipeline_lambda_done", completed=len(results))
    flush_sentry()
    flush_langfuse()
    return {"statusCode": 200, "completed": len(results)}


def morning_handler(event: dict, context: object) -> dict:  # type: ignore[type-arg]
    """8 AM: load yesterday's verdicts → morning notes → Telegram + email."""
    from datetime import date, timedelta

    from analyzer.flags import get_flag
    from analyzer.llm.formatter import format_morning_email_html, format_telegram_morning
    from analyzer.notify import telegram as tg
    from analyzer.notify.email import send_verdict_email
    from analyzer.pipeline.graph_8am import run_8am
    from analyzer.utils.storage import AnalysisStore

    today = date.today()
    yesterday = today - timedelta(days=1)
    pairs = AnalysisStore().load_all(yesterday)

    if not pairs:
        log.warning("no_verdicts_for_morning", date=str(yesterday))
        return {"statusCode": 200, "completed": 0}

    log.info("morning_lambda_start", symbols_count=len(pairs))
    notes = []

    kill_switch = get_flag("kill_switch_publish_verdicts")
    if kill_switch:
        log.warning("kill_switch_active_morning_suppressed", symbols_count=len(pairs))
        return {"statusCode": 200, "completed": 0, "kill_switch": True}

    for symbol, _verdict in pairs:
        try:
            state = run_8am(symbol=symbol, company_name=symbol.replace(".NS", ""))
            if state.morning_note:
                asyncio.run(tg.send_morning_note(format_telegram_morning(state.morning_note)))
                notes.append(state.morning_note)
        except Exception as e:
            log.error("morning_failed", symbol=symbol, error=str(e))

    if notes:
        intact = sum(1 for n in notes if n.status == "INTACT")
        strengthened = sum(1 for n in notes if n.status == "STRENGTHENED")
        weakened = sum(1 for n in notes if n.status == "WEAKENED")
        subject = (
            f"Indian Stock Analyzer · Morning Follow-up · {today.strftime('%d %b %Y')} · "
            f"How are yesterday's calls holding?"
        )
        send_verdict_email(subject, format_morning_email_html(notes, today), html=True)
        log.info("morning_email_sent", intact=intact, strengthened=strengthened, weakened=weakened)

    log.info("morning_lambda_done", completed=len(notes))
    flush_sentry()
    flush_langfuse()
    return {"statusCode": 200, "completed": len(notes)}
