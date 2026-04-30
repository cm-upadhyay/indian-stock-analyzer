"""Outcome tracker — checks whether past predictions played out correctly.

What this does:
    Before analysing a stock today, we look up its most recent verdict (from the last
    1-5 trading days stored in S3/local). We then fetch the actual closing price on the
    day after the prediction and check:
        1. Direction correct? (BUY → price went up, SELL → price went down)
        2. Target hit? (price reached the predicted target within 5 trading days)
        3. Stop triggered? (price fell below stop_loss within 5 trading days)

    The result is stored back as an OutcomeRecord so the /accuracy API endpoint and
    the accuracy page on the dashboard can show running stats.

Why separate from the main verdict?
    The verdict is produced by the 4 PM LLM call. The outcome is checked the NEXT day
    (or later). Storing them separately keeps the verdict immutable — we never go back
    and modify a past JSON. Instead, an OutcomeRecord references it by date+symbol.
"""

from __future__ import annotations

import structlog

from analyzer.data.models import OutcomeRecord, StockVerdict
from analyzer.utils.storage import AnalysisStore, OutcomeStore

log = structlog.get_logger()

_analysis_store = AnalysisStore()
_outcome_store = OutcomeStore()


def check_and_store_outcome(symbol: str, current_price: float) -> OutcomeRecord | None:
    """Look up the most recent verdict for this symbol and evaluate its outcome.

    Called at the START of the 4 PM pipeline (in node_check_outcomes) so the pipeline
    has the freshest outcome data before calling the LLM.

    Steps:
        1. Load the most recent verdict (up to 5 days back)
        2. Compare current_price to predicted entry/target/stop
        3. Store the OutcomeRecord
        4. Return it for logging / memory injection

    Returns None if no past verdict exists (first time we've analysed this stock).
    """
    from datetime import date, timedelta

    run_date = date.today()

    # Walk back up to 5 trading days to find the most recent verdict
    verdict: StockVerdict | None = None
    verdict_date_str: str = ""

    for days_back in range(1, 6):
        check_date = run_date - timedelta(days=days_back)
        v = _analysis_store.load(check_date, symbol)
        if v is not None:
            verdict = v
            verdict_date_str = str(check_date)
            break

    if verdict is None:
        log.info("no_past_verdict", symbol=symbol)
        return None

    # Check if we already evaluated this verdict
    existing = _outcome_store.load(verdict_date_str, symbol)
    if existing and existing.direction_correct is not None:
        log.info("outcome_already_evaluated", symbol=symbol, verdict_date=verdict_date_str)
        return existing

    # Evaluate outcome
    outcome = _evaluate(
        symbol=symbol,
        verdict_date=verdict_date_str,
        outcome_date=str(run_date),
        verdict=verdict,
        current_price=current_price,
    )

    _outcome_store.save(verdict_date_str, symbol, outcome)
    log.info(
        "outcome_evaluated",
        symbol=symbol,
        verdict_date=verdict_date_str,
        signal=verdict.signal,
        direction_correct=outcome.direction_correct,
        target_hit=outcome.target_hit,
        stop_triggered=outcome.stop_triggered,
    )
    return outcome


def _evaluate(
    symbol: str,
    verdict_date: str,
    outcome_date: str,
    verdict: StockVerdict,
    current_price: float,
) -> OutcomeRecord:
    """Compute direction/target/stop outcome given the current price.

    Direction: compared using the entry price as reference.
        BUY:  correct if current_price > entry (or > close_at_verdict if no entry)
        SELL: correct if current_price < entry
        HOLD: always direction-neutral (direction_correct = None for HOLD)

    This is a simplification — a proper backtester would use the closing price on
    the day AFTER the verdict. We use today's current_price as a proxy because we
    don't have historical intraday data for exact next-day close.
    """
    entry = verdict.entry
    target = verdict.target
    stop = verdict.stop_loss
    signal = verdict.signal

    direction_correct: bool | None = None
    target_hit: bool | None = None
    stop_triggered: bool | None = None

    if signal == "BUY" and entry is not None:
        direction_correct = current_price > entry
        if target is not None:
            target_hit = current_price >= target
        if stop is not None:
            stop_triggered = current_price <= stop

    elif signal == "SELL" and entry is not None:
        direction_correct = current_price < entry
        if target is not None:
            target_hit = current_price <= target  # target is lower for SELL
        if stop is not None:
            stop_triggered = current_price >= stop  # stop is above entry for SELL

    # HOLD: no direction to check

    return OutcomeRecord(
        verdict_date=verdict_date,
        symbol=symbol,
        predicted_signal=signal,
        predicted_confidence=verdict.confidence,
        predicted_entry=entry,
        predicted_target=target,
        predicted_stop=stop,
        outcome_date=outcome_date,
        actual_price=current_price,
        direction_correct=direction_correct,
        target_hit=target_hit,
        stop_triggered=stop_triggered,
    )


def load_accuracy_stats() -> dict[str, object]:
    """Compute running accuracy stats across all stored outcomes.

    Used by the GET /accuracy API endpoint.
    Returns a dict with total, correct, accuracy_pct, and breakdown by signal.
    """
    from datetime import date, timedelta

    stats: dict[str, object] = {
        "total": 0,
        "correct": 0,
        "accuracy_pct": 0.0,
        "by_signal": {"BUY": {"total": 0, "correct": 0}, "SELL": {"total": 0, "correct": 0}},
        "target_hit_pct": 0.0,
        "stop_triggered_pct": 0.0,
    }

    all_outcomes: list[OutcomeRecord] = []

    # Scan last 30 days of outcomes
    today = date.today()
    for days_back in range(0, 31):
        check_date = today - timedelta(days=days_back)
        daily = _outcome_store.load_all(str(check_date))
        all_outcomes.extend(daily)

    if not all_outcomes:
        return stats

    directional = [o for o in all_outcomes if o.direction_correct is not None]
    if not directional:
        return stats

    correct = sum(1 for o in directional if o.direction_correct)
    target_hits = [o for o in directional if o.target_hit is not None]
    stop_hits = [o for o in directional if o.stop_triggered is not None]

    stats["total"] = len(directional)
    stats["correct"] = correct
    stats["accuracy_pct"] = round(correct / len(directional) * 100, 1)
    stats["target_hit_pct"] = (
        round(sum(1 for o in target_hits if o.target_hit) / len(target_hits) * 100, 1)
        if target_hits
        else 0.0
    )
    stats["stop_triggered_pct"] = (
        round(sum(1 for o in stop_hits if o.stop_triggered) / len(stop_hits) * 100, 1)
        if stop_hits
        else 0.0
    )

    for signal in ("BUY", "SELL"):
        signal_outcomes = [o for o in directional if o.predicted_signal == signal]
        signal_correct = sum(1 for o in signal_outcomes if o.direction_correct)
        stats["by_signal"][signal] = {  # type: ignore[index]
            "total": len(signal_outcomes),
            "correct": signal_correct,
            "accuracy_pct": (
                round(signal_correct / len(signal_outcomes) * 100, 1) if signal_outcomes else 0.0
            ),
        }

    return stats
