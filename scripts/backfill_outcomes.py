"""Backfill outcome records with the corrected 5-session window evaluation.

The original tracker evaluated each verdict ONCE — usually one trading day after
the verdict, against a single price snapshot — so `target_hit`/`stop_triggered`
were structurally near-impossible and `direction_correct` was measured too early.
This script re-evaluates every stored verdict against full OHLCV history
(yfinance has the historical bars) using the same `_evaluate` the fixed
tracker uses, and rewrites the OutcomeRecords.

Usage:
    uv run python scripts/backfill_outcomes.py            # dry run (default): print summary
    uv run python scripts/backfill_outcomes.py --apply    # write corrected records

Point at prod S3 with:
    STORAGE_BACKEND=s3 S3_BUCKET_NAME=analyzer-data-prod AWS_REGION=us-east-1
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

import pandas as pd
import structlog

from analyzer.adapters.yfinance import get_ohlcv
from analyzer.outcomes.tracker import _evaluate
from analyzer.utils.storage import AnalysisStore, OutcomeStore

log = structlog.get_logger()

_analysis_store = AnalysisStore()
_outcome_store = OutcomeStore()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="write corrected records (default: dry run)"
    )
    parser.add_argument(
        "--days", type=int, default=60, help="how many calendar days back to scan (default 60)"
    )
    args = parser.parse_args()

    today = date.today()
    history_cache: dict[str, pd.DataFrame] = {}

    stats = {
        "scanned": 0,
        "rewritten": 0,
        "final": 0,
        "direction_correct": 0,
        "target_hit": 0,
        "stop_triggered": 0,
        "no_history": 0,
    }

    for days_back in range(1, args.days + 1):
        run_date = today - timedelta(days=days_back)
        verdicts = _analysis_store.load_all(run_date)
        for symbol, verdict in verdicts:
            stats["scanned"] += 1
            if symbol not in history_cache:
                history_cache[symbol] = get_ohlcv(symbol, period="6mo")
            history = history_cache[symbol]

            outcome = _evaluate(
                symbol=symbol,
                verdict_date=str(run_date),
                outcome_date=str(today),
                verdict=verdict,
                current_price=0.0,
                history=history,
                existing=_outcome_store.load(str(run_date), symbol),
            )
            if outcome.sessions_observed == 0:
                stats["no_history"] += 1
                continue

            stats["rewritten"] += 1
            stats["final"] += int(outcome.final)
            stats["direction_correct"] += int(bool(outcome.direction_correct))
            stats["target_hit"] += int(bool(outcome.target_hit))
            stats["stop_triggered"] += int(bool(outcome.stop_triggered))

            if args.apply:
                _outcome_store.save(str(run_date), symbol, outcome)

    mode = "APPLIED" if args.apply else "DRY RUN — nothing written (use --apply)"
    print(f"\n{mode}")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    if args.apply:
        from analyzer.outcomes.tracker import refresh_accuracy_summary

        summary = refresh_accuracy_summary()
        print(
            f"\naccuracy summary refreshed: {summary.get('accuracy_pct')}% over {summary.get('total')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
