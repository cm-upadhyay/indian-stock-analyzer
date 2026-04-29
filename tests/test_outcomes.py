"""Tests for outcomes/tracker.py — outcome evaluation logic."""

from __future__ import annotations

from analyzer.data.models import StockVerdict
from analyzer.outcomes.tracker import _evaluate


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


class TestEvaluateBuyVerdict:
    def test_correct_direction_price_above_entry(self):
        verdict = _make_verdict(signal="BUY", entry=1000)
        outcome = _evaluate("RELIANCE.NS", "2025-01-10", "2025-01-11", verdict, 1050.0)
        assert outcome.direction_correct is True

    def test_wrong_direction_price_below_entry(self):
        verdict = _make_verdict(signal="BUY", entry=1000)
        outcome = _evaluate("RELIANCE.NS", "2025-01-10", "2025-01-11", verdict, 950.0)
        assert outcome.direction_correct is False

    def test_target_hit_when_price_at_target(self):
        verdict = _make_verdict(signal="BUY", entry=1000, target=1100)
        outcome = _evaluate("RELIANCE.NS", "2025-01-10", "2025-01-11", verdict, 1110.0)
        assert outcome.target_hit is True

    def test_target_not_hit_when_price_below(self):
        verdict = _make_verdict(signal="BUY", entry=1000, target=1100)
        outcome = _evaluate("RELIANCE.NS", "2025-01-10", "2025-01-11", verdict, 1050.0)
        assert outcome.target_hit is False

    def test_stop_triggered_when_price_at_stop(self):
        verdict = _make_verdict(signal="BUY", entry=1000, stop_loss=950)
        outcome = _evaluate("RELIANCE.NS", "2025-01-10", "2025-01-11", verdict, 940.0)
        assert outcome.stop_triggered is True

    def test_stop_not_triggered_when_price_above_stop(self):
        verdict = _make_verdict(signal="BUY", entry=1000, stop_loss=950)
        outcome = _evaluate("RELIANCE.NS", "2025-01-10", "2025-01-11", verdict, 980.0)
        assert outcome.stop_triggered is False


class TestEvaluateSellVerdict:
    def test_correct_direction_price_below_entry(self):
        verdict = _make_verdict(signal="SELL", entry=1000, stop_loss=1050, target=900)
        outcome = _evaluate("RELIANCE.NS", "2025-01-10", "2025-01-11", verdict, 950.0)
        assert outcome.direction_correct is True

    def test_wrong_direction_price_above_entry(self):
        verdict = _make_verdict(signal="SELL", entry=1000, stop_loss=1050, target=900)
        outcome = _evaluate("RELIANCE.NS", "2025-01-10", "2025-01-11", verdict, 1050.0)
        assert outcome.direction_correct is False

    def test_target_hit_when_price_at_or_below_target(self):
        verdict = _make_verdict(signal="SELL", entry=1000, stop_loss=1050, target=900)
        outcome = _evaluate("RELIANCE.NS", "2025-01-10", "2025-01-11", verdict, 890.0)
        assert outcome.target_hit is True

    def test_stop_triggered_when_price_above_stop(self):
        verdict = _make_verdict(signal="SELL", entry=1000, stop_loss=1050, target=900)
        outcome = _evaluate("RELIANCE.NS", "2025-01-10", "2025-01-11", verdict, 1060.0)
        assert outcome.stop_triggered is True


class TestEvaluateHoldVerdict:
    def test_hold_direction_correct_is_none(self):
        verdict = _make_verdict(signal="HOLD", entry=None, stop_loss=None, target=None)
        outcome = _evaluate("RELIANCE.NS", "2025-01-10", "2025-01-11", verdict, 1020.0)
        assert outcome.direction_correct is None
        assert outcome.target_hit is None
        assert outcome.stop_triggered is None


class TestOutcomeRecordFields:
    def test_outcome_record_fields_populated(self):
        verdict = _make_verdict(signal="BUY", entry=1000, stop_loss=950, target=1100)
        outcome = _evaluate("RELIANCE.NS", "2025-01-10", "2025-01-11", verdict, 1050.0)
        assert outcome.verdict_date == "2025-01-10"
        assert outcome.symbol == "RELIANCE.NS"
        assert outcome.predicted_signal == "BUY"
        assert outcome.predicted_entry == 1000
        assert outcome.outcome_date == "2025-01-11"
        assert outcome.actual_price == 1050.0
