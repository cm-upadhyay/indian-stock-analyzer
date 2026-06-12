"""Outcome tracker — checks whether past predictions played out correctly.

What this does:
    Before analysing a stock today, we look up its recent verdicts (up to 10 calendar
    days back in S3/local). For each verdict whose evaluation window is still open we
    fetch the daily OHLCV bars since the verdict date and check:
        1. Direction correct? (BUY → close above entry, SELL → close below entry,
           measured at the close of the 5th trading session after the verdict)
        2. Target hit? (High/Low reached the predicted target on ANY session in the window)
        3. Stop triggered? (High/Low breached the stop on ANY session in the window)

    A record is re-evaluated on every encounter until 5 trading sessions have elapsed,
    then marked `final` and frozen. Direction stays None until the window closes —
    the PRD metric is "direction 5 trading days out", not "direction the next morning".

    The result is stored back as an OutcomeRecord so the /accuracy API endpoint and
    the accuracy page on the dashboard can show running stats.

Why separate from the main verdict?
    The verdict is produced by the 4 PM LLM call. The outcome is checked on later
    days. Storing them separately keeps the verdict immutable — we never go back
    and modify a past JSON. Instead, an OutcomeRecord references it by date+symbol.
"""

from __future__ import annotations

import pandas as pd
import structlog

from analyzer.adapters.yfinance import get_price_history
from analyzer.data.models import OutcomeRecord, StockVerdict
from analyzer.utils.storage import AnalysisStore, OutcomeStore

log = structlog.get_logger()

_analysis_store = AnalysisStore()
_outcome_store = OutcomeStore()

# The PRD metric: direction measured 5 trading sessions after the verdict.
WINDOW_SESSIONS = 5
# Calendar-day lookback that comfortably contains 5 trading sessions
# (weekends + NSE holidays).
_LOOKBACK_DAYS = 10


def check_and_store_outcome(symbol: str, current_price: float) -> OutcomeRecord | None:
    """Evaluate every open verdict for this symbol against price history.

    Called at the START of the 4 PM pipeline (in node_check_outcomes) so the pipeline
    has the freshest outcome data before calling the LLM.

    Steps:
        1. Walk back up to 10 calendar days; for each stored verdict that is not
           yet `final`, (re-)evaluate it against the OHLCV window since its date
        2. Store each updated OutcomeRecord
        3. Return the most recent outcome for logging / memory injection

    Returns None if no past verdict exists (first time we've analysed this stock).
    """
    from datetime import date, timedelta

    run_date = date.today()
    history = get_price_history(symbol, period="1mo")

    latest: OutcomeRecord | None = None

    for days_back in range(1, _LOOKBACK_DAYS + 1):
        check_date = run_date - timedelta(days=days_back)
        verdict = _analysis_store.load(check_date, symbol)
        if verdict is None:
            continue
        verdict_date_str = str(check_date)

        existing = _outcome_store.load(verdict_date_str, symbol)
        if existing is not None and existing.final:
            latest = latest or existing
            continue

        outcome = _evaluate(
            symbol=symbol,
            verdict_date=verdict_date_str,
            outcome_date=str(run_date),
            verdict=verdict,
            current_price=current_price,
            history=history,
            existing=existing,
        )
        _outcome_store.save(verdict_date_str, symbol, outcome)
        log.info(
            "outcome_evaluated",
            symbol=symbol,
            verdict_date=verdict_date_str,
            signal=verdict.signal,
            sessions_observed=outcome.sessions_observed,
            final=outcome.final,
            direction_correct=outcome.direction_correct,
            target_hit=outcome.target_hit,
            stop_triggered=outcome.stop_triggered,
        )
        latest = latest or outcome

    if latest is None:
        log.info("no_past_verdict", symbol=symbol)
    return latest


def _evaluate(
    symbol: str,
    verdict_date: str,
    outcome_date: str,
    verdict: StockVerdict,
    current_price: float,
    history: pd.DataFrame,
    existing: OutcomeRecord | None = None,
) -> OutcomeRecord:
    """Compute direction/target/stop outcome from the OHLCV window after the verdict.

    Direction (close of the 5th trading session vs. entry):
        BUY:  correct if close > entry
        SELL: correct if close < entry
        HOLD: always direction-neutral (direction_correct = None)
        Stays None until 5 sessions have elapsed — partial windows are provisional.

    Target / stop use the intraday extremes of EVERY session in the window:
        BUY:  target_hit if any High ≥ target · stop_triggered if any Low ≤ stop
        SELL: target_hit if any Low ≤ target · stop_triggered if any High ≥ stop

    If price history is unavailable, the existing record is preserved (never
    regress a previous evaluation) and the record stays non-final.
    """
    from datetime import date

    entry = verdict.entry
    target = verdict.target
    stop = verdict.stop_loss
    signal = verdict.signal

    window = _window_after(history, date.fromisoformat(verdict_date))
    sessions = len(window)

    if sessions == 0:
        # No bars yet (or fetch failed). Keep whatever we knew before.
        if existing is not None:
            return existing
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
        )

    final = sessions >= WINDOW_SESSIONS
    highs = window["High"]
    lows = window["Low"]
    closes = window["Close"]
    # Direction is judged at the close of session 5; until then the window is open.
    ref_close = float(closes.iloc[WINDOW_SESSIONS - 1]) if final else float(closes.iloc[-1])

    direction_correct: bool | None = None
    target_hit: bool | None = None
    stop_triggered: bool | None = None

    if signal == "BUY" and entry is not None:
        if final:
            direction_correct = ref_close > entry
        if target is not None:
            target_hit = bool((highs >= target).any())
        if stop is not None:
            stop_triggered = bool((lows <= stop).any())

    elif signal == "SELL" and entry is not None:
        if final:
            direction_correct = ref_close < entry
        if target is not None:
            target_hit = bool((lows <= target).any())  # target is lower for SELL
        if stop is not None:
            stop_triggered = bool((highs >= stop).any())  # stop is above entry for SELL

    # HOLD: no direction to check — the window still closes after 5 sessions.

    return OutcomeRecord(
        verdict_date=verdict_date,
        symbol=symbol,
        predicted_signal=signal,
        predicted_confidence=verdict.confidence,
        predicted_entry=entry,
        predicted_target=target,
        predicted_stop=stop,
        outcome_date=outcome_date,
        actual_price=ref_close,
        direction_correct=direction_correct,
        target_hit=target_hit,
        stop_triggered=stop_triggered,
        sessions_observed=sessions,
        final=final,
    )


def _window_after(history: pd.DataFrame, verdict_date: object) -> pd.DataFrame:
    """Rows of `history` strictly after the verdict date (the sessions being judged)."""
    if history.empty or not isinstance(history.index, pd.DatetimeIndex):
        return pd.DataFrame()
    mask = [d > verdict_date for d in history.index.date]
    window = history.loc[mask]
    return window.head(WINDOW_SESSIONS) if len(window) > WINDOW_SESSIONS else window


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
