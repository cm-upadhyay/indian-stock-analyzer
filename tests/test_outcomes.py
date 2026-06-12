"""Tests for outcomes/tracker.py — 5-session window outcome evaluation."""

from __future__ import annotations

import pandas as pd

from analyzer.data.models import OutcomeRecord, StockVerdict
from analyzer.outcomes.tracker import WINDOW_SESSIONS, _evaluate

VERDICT_DATE = "2025-01-10"  # Friday
OUTCOME_DATE = "2025-01-20"


def _make_verdict(**kwargs) -> StockVerdict:  # type: ignore[no-untyped-def]
    defaults = {
        "signal": "BUY",
        "confidence": 0.72,
        "entry": 1000,
        "stop_loss": 950,
        "target": 1100,
        "whats_happening": "Technical breakout.",
        "why_it_matters": "Momentum building.",
        "watch_out_for": "Market correction risk.",
        "trader_action": "Enter at 1000.",
        "investor_action": "Accumulate on dips.",
    }
    defaults.update(kwargs)
    return StockVerdict(**defaults)


def _history(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> pd.DataFrame:
    """OHLCV frame whose sessions start the first trading day after VERDICT_DATE."""
    n = len(closes)
    return pd.DataFrame(
        {
            "High": highs or [c + 5 for c in closes],
            "Low": lows or [c - 5 for c in closes],
            "Close": closes,
        },
        index=pd.date_range("2025-01-13", periods=n, freq="B"),
    )


def _run(
    verdict: StockVerdict,
    history: pd.DataFrame,
    existing: OutcomeRecord | None = None,
) -> OutcomeRecord:
    return _evaluate(
        symbol="RELIANCE.NS",
        verdict_date=VERDICT_DATE,
        outcome_date=OUTCOME_DATE,
        verdict=verdict,
        current_price=0.0,
        history=history,
        existing=existing,
    )


class TestDirectionAtWindowClose:
    def test_buy_correct_when_session5_close_above_entry(self):
        outcome = _run(
            _make_verdict(signal="BUY", entry=1000), _history([1010, 1005, 998, 1020, 1030])
        )
        assert outcome.direction_correct is True
        assert outcome.final is True
        assert outcome.sessions_observed == WINDOW_SESSIONS

    def test_buy_wrong_when_session5_close_below_entry(self):
        outcome = _run(
            _make_verdict(signal="BUY", entry=1000), _history([1010, 1005, 998, 1020, 990])
        )
        assert outcome.direction_correct is False

    def test_direction_judged_at_session5_not_later(self):
        # Session 5 closes below entry; later sessions rally — must not count.
        history = _history([990, 985, 980, 975, 970, 1100, 1200])
        outcome = _run(_make_verdict(signal="BUY", entry=1000), history)
        assert outcome.direction_correct is False

    def test_sell_correct_when_session5_close_below_entry(self):
        verdict = _make_verdict(signal="SELL", entry=1000, stop_loss=1050, target=900)
        outcome = _run(verdict, _history([990, 985, 992, 980, 970]))
        assert outcome.direction_correct is True

    def test_sell_wrong_when_session5_close_above_entry(self):
        verdict = _make_verdict(signal="SELL", entry=1000, stop_loss=1050, target=900)
        outcome = _run(verdict, _history([990, 1010, 1020, 1030, 1040]))
        assert outcome.direction_correct is False


class TestProvisionalWindow:
    def test_direction_none_before_5_sessions(self):
        outcome = _run(_make_verdict(signal="BUY", entry=1000), _history([1050, 1060]))
        assert outcome.direction_correct is None
        assert outcome.final is False
        assert outcome.sessions_observed == 2

    def test_target_evaluated_even_in_open_window(self):
        outcome = _run(
            _make_verdict(signal="BUY", entry=1000, target=1100),
            _history([1099], highs=[1101]),
        )
        assert outcome.target_hit is True
        assert outcome.final is False


class TestTargetAndStopUseIntradayExtremes:
    def test_buy_target_hit_by_intraday_high(self):
        # Close never reaches 1100 but day 3's high does.
        history = _history([1010, 1020, 1090, 1015, 1005], highs=[1015, 1025, 1105, 1020, 1010])
        outcome = _run(_make_verdict(signal="BUY", entry=1000, target=1100), history)
        assert outcome.target_hit is True

    def test_buy_target_not_hit(self):
        outcome = _run(
            _make_verdict(signal="BUY", entry=1000, target=1100),
            _history([1010, 1020, 1030, 1040, 1050]),
        )
        assert outcome.target_hit is False

    def test_buy_stop_triggered_by_intraday_low(self):
        history = _history([1010, 1005, 960, 1000, 1010], lows=[1005, 1000, 945, 995, 1005])
        outcome = _run(_make_verdict(signal="BUY", entry=1000, stop_loss=950), history)
        assert outcome.stop_triggered is True

    def test_sell_target_hit_by_intraday_low(self):
        verdict = _make_verdict(signal="SELL", entry=1000, stop_loss=1050, target=900)
        history = _history([950, 940, 920, 930, 925], lows=[945, 935, 895, 925, 920])
        outcome = _run(verdict, history)
        assert outcome.target_hit is True

    def test_sell_stop_triggered_by_intraday_high(self):
        verdict = _make_verdict(signal="SELL", entry=1000, stop_loss=1050, target=900)
        history = _history([1010, 1020, 1040, 1030, 1020], highs=[1015, 1025, 1055, 1035, 1025])
        outcome = _run(verdict, history)
        assert outcome.stop_triggered is True


class TestHoldVerdict:
    def test_hold_direction_none_but_window_closes(self):
        verdict = _make_verdict(signal="HOLD", entry=None, stop_loss=None, target=None)
        outcome = _run(verdict, _history([1010, 1015, 1020, 1025, 1030]))
        assert outcome.direction_correct is None
        assert outcome.target_hit is None
        assert outcome.stop_triggered is None
        assert outcome.final is True


class TestNoHistoryFallback:
    def test_empty_history_preserves_existing_record(self):
        existing = OutcomeRecord(
            verdict_date=VERDICT_DATE,
            symbol="RELIANCE.NS",
            predicted_signal="BUY",
            predicted_confidence=0.72,
            predicted_entry=1000,
            predicted_target=1100,
            predicted_stop=950,
            outcome_date="2025-01-14",
            actual_price=1050.0,
            target_hit=True,
            sessions_observed=2,
        )
        outcome = _run(_make_verdict(), pd.DataFrame(), existing=existing)
        assert outcome is existing  # never regress a previous evaluation

    def test_empty_history_no_existing_yields_open_record(self):
        outcome = _run(_make_verdict(), pd.DataFrame())
        assert outcome.final is False
        assert outcome.direction_correct is None
        assert outcome.sessions_observed == 0


class TestOutcomeRecordFields:
    def test_outcome_record_fields_populated(self):
        outcome = _run(
            _make_verdict(signal="BUY", entry=1000, stop_loss=950, target=1100),
            _history([1010, 1020, 1030, 1040, 1050]),
        )
        assert outcome.verdict_date == VERDICT_DATE
        assert outcome.symbol == "RELIANCE.NS"
        assert outcome.predicted_signal == "BUY"
        assert outcome.predicted_entry == 1000
        assert outcome.outcome_date == OUTCOME_DATE
        assert outcome.actual_price == 1050.0  # session-5 close
