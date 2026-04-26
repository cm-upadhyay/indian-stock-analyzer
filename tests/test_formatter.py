"""Unit tests for llm/formatter.py — pure display logic, no I/O."""

from analyzer.data.models import ScoringResult, StockVerdict
from analyzer.llm.formatter import _to_int, format_telegram, format_verdict


def _make_scoring(grade: str = "LEAN BUY") -> ScoringResult:
    return ScoringResult(
        tech_score=0.3,
        fund_score=0.2,
        india_score=0.5,
        combined_score=0.33,
        grade=grade,
        tech_buy=8,
        tech_neutral=3,
        tech_sell=1,
        fund_buy=9,
        fund_neutral=4,
        fund_sell=2,
        india_buy=3,
        india_neutral=1,
        india_sell=0,
        total_buy=20,
        total_neutral=8,
        total_sell=3,
        total_votes=31,
        tech_summary="LEAN BUY     8B · 3N · 1S",
        fund_summary="LEAN BUY     9B · 4N · 2S",
        india_summary="STRONG BUY   3B · 1N · 0S",
        combined_summary="LEAN BUY     20B · 8N · 3S  (score: +0.33)",
    )


def _make_verdict(signal: str = "BUY") -> StockVerdict:
    return StockVerdict(
        signal=signal,
        confidence=0.68,
        entry=1350,
        stop_loss=1260,
        target=1500,
        whats_happening="The stock has been rising steadily.",
        why_it_matters="Revenue growth is strong at 18% YoY.",
        watch_out_for="Earnings in 10 days may cause volatility.",
        trader_action="Enter around ₹1,350. Stop at ₹1,260. Target ₹1,500.",
        investor_action="Accumulate on dips below ₹1,300.",
    )


class TestToInt:
    def test_int_passthrough(self):
        assert _to_int(1350) == 1350

    def test_float_truncated(self):
        assert _to_int(1350.9) == 1350

    def test_plain_string(self):
        assert _to_int("1350") == 1350

    def test_string_with_rupee(self):
        assert _to_int("₹1,350") == 1350

    def test_range_string_takes_first(self):
        assert _to_int("₹1,345–₹1,375") == 1345

    def test_string_with_commas(self):
        assert _to_int("1,23,456") == 123456

    def test_empty_string_returns_zero(self):
        assert _to_int("no numbers here") == 0


class TestFormatVerdict:
    def test_buy_contains_entry_stop_target(self):
        out = format_verdict(
            "RELIANCE.NS",
            "Reliance Industries",
            1320.0,
            0.85,
            _make_scoring(),
            _make_verdict("BUY"),
        )
        assert "1,350" in out
        assert "1,260" in out
        assert "1,500" in out

    def test_hold_no_trade_message(self):
        hold_verdict = _make_verdict("HOLD")
        hold_verdict = hold_verdict.model_copy(update={"stop_loss": 0, "target": 0})
        out = format_verdict(
            "RELIANCE.NS",
            "Reliance Industries",
            1320.0,
            None,
            _make_scoring("NEUTRAL"),
            hold_verdict,
        )
        assert "No trade" in out

    def test_contains_company_name(self):
        out = format_verdict(
            "RELIANCE.NS", "Reliance Industries", 1320.0, 0.85, _make_scoring(), _make_verdict()
        )
        assert "RELIANCE INDUSTRIES" in out

    def test_contains_confidence(self):
        out = format_verdict(
            "RELIANCE.NS", "Reliance Industries", 1320.0, 0.85, _make_scoring(), _make_verdict()
        )
        assert "68%" in out

    def test_contains_signal_sections(self):
        out = format_verdict(
            "RELIANCE.NS", "Reliance Industries", 1320.0, 0.85, _make_scoring(), _make_verdict()
        )
        assert "What's Happening" in out
        assert "Why It Matters" in out
        assert "Watch Out For" in out

    def test_sell_signal_icon(self):
        out = format_verdict(
            "RELIANCE.NS",
            "Reliance",
            1320.0,
            None,
            _make_scoring("LEAN SELL"),
            _make_verdict("SELL"),
        )
        assert "↓" in out


class TestFormatTelegram:
    def test_contains_symbol(self):
        out = format_telegram(
            "RELIANCE.NS", "Reliance Industries", 1320.0, _make_verdict(), _make_scoring()
        )
        assert "RELIANCE" in out

    def test_contains_signal(self):
        out = format_telegram(
            "RELIANCE.NS", "Reliance Industries", 1320.0, _make_verdict("BUY"), _make_scoring()
        )
        assert "BUY" in out

    def test_hold_no_entry(self):
        hold_v = _make_verdict("HOLD")
        out = format_telegram("RELIANCE.NS", "Reliance", 1320.0, hold_v, _make_scoring("NEUTRAL"))
        # Entry/stop/target line should not appear for HOLD
        assert "Entry" not in out
