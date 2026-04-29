"""CLI entry point — python -m analyzer.

4 PM mode (default):  python -m analyzer
Watchlist mode:       python -m analyzer --symbols RELIANCE,TCS
8 AM mode:            python -m analyzer --morning
Dry run:              python -m analyzer --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date

import structlog
from dotenv import load_dotenv

from analyzer.utils.logging import configure_logging

load_dotenv()
configure_logging()

log = structlog.get_logger()


def _validate_symbols(symbols: list[str]) -> list[str]:
    """Return list of symbols that don't match the expected NSE format."""
    import re

    pattern = re.compile(r"^[A-Z0-9&-]{1,20}\.NS$")
    return [s for s in symbols if not pattern.match(s)]


def _validate_env(dry_run: bool) -> list[str]:
    required = ["OPENAI_API_KEY"]
    if not dry_run:
        # Telegram vars only matter when actually delivering — not in dry-run
        required += ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_IDS"]
    return [k for k in required if not os.getenv(k)]


def _backfill_pending_outcomes(today_symbols: list[str]) -> None:
    """Evaluate outcomes for verdicts from the last 10 days that haven't been scored yet.

    Stocks not picked by today's screener never enter the per-symbol pipeline, so
    their past verdicts would go unscored forever. This pre-batch scan closes that gap:
    for every verdict in the last 10 days that has no OutcomeRecord yet, we fetch the
    current price via yfinance and score it now.

    Called once at the start of _run_4pm(), before the per-symbol loop.
    Only yfinance calls are added (free). No Tavily, no main LLM call.
    """
    from datetime import date, timedelta

    import yfinance as yf

    from analyzer.outcomes.tracker import check_and_store_outcome
    from analyzer.utils.storage import AnalysisStore, OutcomeStore

    analysis_store = AnalysisStore()
    outcome_store = OutcomeStore()
    today = date.today()

    for days_back in range(1, 11):
        check_date = today - timedelta(days=days_back)
        pairs = analysis_store.load_all(check_date)
        for sym, _ in pairs:
            if sym in today_symbols:
                continue  # will be handled inside the pipeline
            if outcome_store.load(str(check_date), sym) is not None:
                continue  # already scored
            try:
                price = yf.Ticker(sym).fast_info.last_price or 0.0
                if price > 0:
                    outcome = check_and_store_outcome(sym, price)
                    if outcome:
                        from analyzer.memory.store import MemoryStore

                        MemoryStore().add_outcome_result(sym, outcome)
                        log.info("backfill_outcome", symbol=sym, verdict_date=str(check_date))
            except Exception as e:
                log.warning("backfill_outcome_failed", symbol=sym, error=str(e))


def _run_4pm(symbols: list[str], dry_run: bool, no_notify: bool) -> None:
    from analyzer.llm.formatter import format_telegram, format_verdict
    from analyzer.notify import telegram as tg
    from analyzer.notify.email import send_verdict_email
    from analyzer.pipeline.graph_4pm import run_4pm

    log.info("4pm_pipeline_start", symbols=symbols, dry_run=dry_run)

    _backfill_pending_outcomes(symbols)

    for symbol in symbols:
        log.info("analyzing", symbol=symbol)
        state = run_4pm(symbol)

        if state.error:
            log.error("pipeline_error", symbol=symbol, error=state.error)
            continue

        if state.verdict is None or state.stock is None or state.scoring is None:
            log.error("incomplete_state", symbol=symbol)
            continue

        terminal_output = format_verdict(
            symbol=state.stock.symbol,
            company_name=state.stock.company_name,
            current_price=state.stock.current_price,
            beta=state.fund.beta if state.fund else None,
            scoring=state.scoring,
            verdict=state.verdict,
        )
        print(terminal_output)

        if not dry_run and not no_notify:
            tg_text = format_telegram(
                symbol=state.stock.symbol,
                company_name=state.stock.company_name,
                current_price=state.stock.current_price,
                verdict=state.verdict,
                scoring=state.scoring,
            )
            asyncio.run(tg.send_verdict(tg_text))
            send_verdict_email(
                subject=f"[{state.verdict.signal}] {state.stock.company_name} — {date.today()}",
                body=terminal_output,
            )

    # Post-batch: extract cross-stock patterns from accumulated outcomes.
    # One gpt-4o-mini call per day. Skipped automatically if <5 outcomes exist.
    if not dry_run:
        try:
            from analyzer.memory.store import MemoryStore

            MemoryStore().extract_and_store_patterns()
        except Exception as e:
            log.warning("pattern_extraction_failed", error=str(e))


def _run_morning(symbols: list[str], dry_run: bool, no_notify: bool) -> None:
    from analyzer.notify import telegram as tg
    from analyzer.pipeline.graph_8am import run_8am

    log.info("8am_pipeline_start", symbols=symbols)

    for symbol in symbols:
        state = run_8am(symbol=symbol, company_name=symbol.replace(".NS", ""))

        if state.error:
            log.error("morning_error", symbol=symbol, error=state.error)
            continue

        if state.morning_note is None:
            continue

        print(f"\nMORNING UPDATE · {symbol}")
        print("─" * 64)
        print(state.morning_note.morning_text)
        print("─" * 64)

        if not dry_run and not no_notify:
            asyncio.run(tg.send_morning_note(state.morning_note.morning_text))


def main() -> None:
    parser = argparse.ArgumentParser(description="Indian Stock Analyzer")
    parser.add_argument("--symbols", help="Comma-separated symbols (skips screener)")
    parser.add_argument("--morning", action="store_true", help="Run 8 AM morning note pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Skip notifications and storage")
    parser.add_argument("--no-notify", action="store_true", help="Run pipeline but skip delivery")
    args = parser.parse_args()

    missing = _validate_env(dry_run=args.dry_run)
    if missing:
        print(f"Missing required env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
        symbols = [s if s.endswith(".NS") else f"{s}.NS" for s in symbols]
        invalid = _validate_symbols(symbols)
        if invalid:
            print(
                f"Invalid symbol format: {', '.join(invalid)} — expected e.g. RELIANCE.NS",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        if args.morning:
            # Morning mode with no explicit symbols reads all of yesterday's verdicts
            from datetime import timedelta

            from analyzer.utils.storage import AnalysisStore

            yesterday = date.today() - timedelta(days=1)
            pairs = AnalysisStore().load_all(yesterday)
            symbols = [sym for sym, _ in pairs]
        else:
            from analyzer.screener import run_screener

            symbols = run_screener()

    if not symbols:
        log.warning("no_symbols_to_analyze")
        sys.exit(0)

    if args.morning:
        _run_morning(symbols, args.dry_run, args.no_notify)
    else:
        _run_4pm(symbols, args.dry_run, args.no_notify)


if __name__ == "__main__":
    main()
