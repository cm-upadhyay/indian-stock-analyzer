"""Tests for guardrails/schema_guards.py — business-rule validators on LLM verdicts."""

from __future__ import annotations

from analyzer.data.models import StockVerdict
from analyzer.guardrails.schema_guards import (
    check_banned_phrases,
    check_confidence_threshold,
    check_entry_price_range,
    check_stop_loss_valid,
)


def _make_verdict(**kwargs) -> StockVerdict:  # type: ignore[no-untyped-def]
    defaults = {
        "signal": "BUY",
        "confidence": 0.72,
        "entry": 1320,
        "stop_loss": 1254,
        "target": 1452,
        "whats_happening": "Price broke above resistance with volume.",
        "why_it_matters": "Institutional accumulation suggests sustained rally.",
        "watch_out_for": "Broad market correction could invalidate the setup.",
        "trader_action": "Enter near 1320. Stop at 1254. Target 1452.",
        "investor_action": "Accumulate on dips below 1330.",
    }
    defaults.update(kwargs)
    return StockVerdict(**defaults)


# ── Entry price range ─────────────────────────────────────────────────────────


class TestEntryPriceRange:
    def test_valid_within_5pct(self):
        assert check_entry_price_range(1320, 1330.0) is None

    def test_valid_exact_match(self):
        assert check_entry_price_range(1000, 1000.0) is None

    def test_invalid_too_far(self):
        result = check_entry_price_range(2000, 1000.0)
        assert result is not None
        assert "5%" in result or "away" in result

    def test_none_entry_skipped(self):
        assert check_entry_price_range(None, 1000.0) is None

    def test_zero_current_price_skipped(self):
        assert check_entry_price_range(1000, 0.0) is None

    def test_boundary_exactly_5pct(self):
        # Exactly 5% away should still be valid (ratio == 0.05 is not > 0.05)
        assert check_entry_price_range(950, 1000.0) is None

    def test_just_over_5pct_invalid(self):
        result = check_entry_price_range(940, 1000.0)
        assert result is not None


# ── Stop-loss validity ────────────────────────────────────────────────────────


class TestStopLossValid:
    def test_valid_buy_stop_3pct_below(self):
        assert check_stop_loss_valid("BUY", 1000, 970) is None  # 3% below

    def test_invalid_buy_stop_above_entry(self):
        result = check_stop_loss_valid("BUY", 1000, 1050)
        assert result is not None
        assert "below" in result.lower()

    def test_invalid_buy_stop_too_tight(self):
        # Only 1% below — less than 2% minimum
        result = check_stop_loss_valid("BUY", 1000, 990)
        assert result is not None

    def test_invalid_buy_stop_too_wide(self):
        # 15% below — more than 8% maximum
        result = check_stop_loss_valid("BUY", 1000, 850)
        assert result is not None

    def test_valid_sell_stop_3pct_above(self):
        assert check_stop_loss_valid("SELL", 1000, 1030) is None  # 3% above

    def test_invalid_sell_stop_below_entry(self):
        result = check_stop_loss_valid("SELL", 1000, 950)
        assert result is not None
        assert "above" in result.lower()

    def test_hold_skipped(self):
        assert check_stop_loss_valid("HOLD", None, None) is None

    def test_none_values_skipped(self):
        assert check_stop_loss_valid("BUY", None, None) is None


# ── Confidence threshold ──────────────────────────────────────────────────────


class TestConfidenceThreshold:
    def test_high_confidence_buy_valid(self):
        assert check_confidence_threshold("BUY", 0.72) is None

    def test_low_confidence_buy_invalid(self):
        result = check_confidence_threshold("BUY", 0.45)
        assert result is not None
        assert "HOLD" in result

    def test_exactly_0_6_valid(self):
        assert check_confidence_threshold("BUY", 0.60) is None

    def test_hold_any_confidence_valid(self):
        assert check_confidence_threshold("HOLD", 0.30) is None

    def test_low_confidence_sell_invalid(self):
        result = check_confidence_threshold("SELL", 0.55)
        assert result is not None


# ── Banned phrases ────────────────────────────────────────────────────────────


class TestBannedPhrases:
    def test_no_violations(self):
        v = _make_verdict()
        assert check_banned_phrases(v) == []

    def test_guaranteed_in_trader_action(self):
        v = _make_verdict(trader_action="This is guaranteed to go up.")
        violations = check_banned_phrases(v)
        assert len(violations) == 1
        assert "guaranteed" in violations[0]

    def test_risk_free_in_investor_action(self):
        v = _make_verdict(investor_action="This is a risk-free investment.")
        violations = check_banned_phrases(v)
        assert any("risk-free" in viol for viol in violations)

    def test_case_insensitive(self):
        v = _make_verdict(why_it_matters="This stock is GUARANTEED to rise.")
        violations = check_banned_phrases(v)
        assert violations

    def test_multiple_violations_across_fields(self):
        v = _make_verdict(
            whats_happening="This is risk-free.",
            why_it_matters="Guaranteed returns.",
        )
        violations = check_banned_phrases(v)
        assert len(violations) >= 2
