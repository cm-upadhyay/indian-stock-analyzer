"""Lambda handler entry points for the two pipeline functions.

analyzer-pipeline (3:30 PM IST EventBridge trigger):
    CMD = ["analyzer.pipeline.lambda_handlers.pipeline_handler"]

analyzer-morning (8:00 AM IST EventBridge trigger):
    CMD = ["analyzer.pipeline.lambda_handlers.morning_handler"]
"""

from __future__ import annotations

import asyncio
import os

import structlog
from dotenv import load_dotenv

from analyzer.utils.logging import configure_logging

load_dotenv()
configure_logging()
log = structlog.get_logger()

from analyzer.utils.secrets import load_secrets_from_ssm  # noqa: E402

load_secrets_from_ssm()


def pipeline_handler(event: dict, context: object) -> dict:  # type: ignore[type-arg]
    """4 PM: screener → 30 stocks → full analysis → store verdicts."""
    import re
    from datetime import date

    from analyzer.llm.formatter import format_telegram
    from analyzer.notify import telegram as tg
    from analyzer.pipeline.graph_4pm import run_4pm
    from analyzer.screener import run_screener
    from analyzer.utils.storage import AnalysisStore

    symbols_env = os.getenv("SYMBOLS", "")
    if symbols_env:
        raw_symbols = [s.strip().upper() for s in symbols_env.split(",")]
        # Validate format to reject garbage input early
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

    for symbol in symbols:
        # Idempotency: if Lambda fires twice (AWS at-least-once), skip already-processed symbols
        if store.load(today, symbol) is not None:
            log.info("already_processed_skipping", symbol=symbol, date=str(today))
            continue

        try:
            state = run_4pm(symbol)
            if state.verdict and state.stock and state.scoring:
                store.save(today, symbol, state.verdict)
                results.append(
                    {
                        "symbol": symbol,
                        "signal": state.verdict.signal,
                        "confidence": state.verdict.confidence,
                    }
                )
                tg_text = format_telegram(
                    symbol=state.stock.symbol,
                    company_name=state.stock.company_name,
                    current_price=state.stock.current_price,
                    verdict=state.verdict,
                    scoring=state.scoring,
                )
                asyncio.run(tg.send_verdict(tg_text))
        except Exception as e:
            log.error("stock_failed", symbol=symbol, error=str(e))

    log.info("pipeline_lambda_done", completed=len(results))
    return {"statusCode": 200, "completed": len(results)}


def morning_handler(event: dict, context: object) -> dict:  # type: ignore[type-arg]
    """8 AM: load yesterday's verdicts → global cues → morning note → deliver."""
    from datetime import date, timedelta

    from analyzer.notify import telegram as tg
    from analyzer.pipeline.graph_8am import run_8am
    from analyzer.utils.storage import AnalysisStore

    yesterday = date.today() - timedelta(days=1)
    pairs = AnalysisStore().load_all(yesterday)

    if not pairs:
        log.warning("no_verdicts_for_morning", date=str(yesterday))
        return {"statusCode": 200, "completed": 0}

    log.info("morning_lambda_start", symbols_count=len(pairs))
    completed = 0

    for symbol, _verdict in pairs:
        try:
            state = run_8am(symbol=symbol, company_name=symbol.replace(".NS", ""))
            if state.morning_note:
                asyncio.run(tg.send_morning_note(state.morning_note.morning_text))
                completed += 1
        except Exception as e:
            log.error("morning_failed", symbol=symbol, error=str(e))

    log.info("morning_lambda_done", completed=completed)
    return {"statusCode": 200, "completed": completed}
