"""Unit tests for llm/formatter.py — pure display logic, no I/O."""

from datetime import date

from analyzer.data.models import MorningNote, ScoringResult, StockVerdict
from analyzer.llm.formatter import (
    _to_int,
    format_email_html,
    format_morning_email_html,
    format_telegram,
    format_telegram_morning,
    format_verdict,
)


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


def _make_morning_note(status: str = "INTACT", signal: str = "BUY") -> MorningNote:
    return MorningNote(
        symbol="RELIANCE.NS",
        company_name="Reliance Industries",
        previous_signal=signal,
        morning_text="Market opened flat; no material change to the thesis.",
        status=status,
    )


def _make_stock(signal: str = "BUY") -> dict:
    return {
        "symbol": "RELIANCE.NS",
        "company_name": "Reliance Industries",
        "current_price": 1320.0,
        "beta": 0.85,
        "scoring": _make_scoring(),
        "verdict": _make_verdict(signal),
    }


class TestFormatTelegramMorning:
    def test_contains_company_and_status(self):
        out = format_telegram_morning(_make_morning_note("INTACT", "BUY"))
        assert "Reliance Industries" in out
        assert "INTACT" in out
        assert "BUY" in out

    def test_weakened_shows_warning_icon(self):
        out = format_telegram_morning(_make_morning_note("WEAKENED", "SELL"))
        assert "⚠️" in out

    def test_strengthened_shows_green_icon(self):
        out = format_telegram_morning(_make_morning_note("STRENGTHENED", "BUY"))
        assert "🟢" in out

    def test_symbol_stripped_of_ns(self):
        out = format_telegram_morning(_make_morning_note())
        assert "RELIANCE.NS" not in out
        assert "RELIANCE" in out

    def test_morning_text_present(self):
        out = format_telegram_morning(_make_morning_note())
        assert "no material change" in out


class TestFormatEmailHtml:
    def test_html_contains_company_and_date(self):
        html = format_email_html([_make_stock("BUY")], date(2024, 4, 26))
        assert "Reliance Industries" in html
        assert "26 Apr 2024" in html

    def test_buy_shows_entry_and_stop(self):
        html = format_email_html([_make_stock("BUY")], date(2024, 4, 26))
        assert "1,350" in html
        assert "1,260" in html

    def test_hold_shows_no_trade_message(self):
        hold_v = _make_verdict("HOLD").model_copy(update={"entry": None})
        stock = {
            "symbol": "INFY.NS",
            "company_name": "Infosys",
            "current_price": 1800.0,
            "beta": None,
            "scoring": _make_scoring("NEUTRAL"),
            "verdict": hold_v,
        }
        html = format_email_html([stock], date(2024, 4, 26))
        assert "No trade" in html

    def test_summary_badges_for_all_signals(self):
        stocks = [_make_stock("BUY"), _make_stock("HOLD"), _make_stock("SELL")]
        html = format_email_html(stocks, date(2024, 4, 26))
        assert "BUY" in html
        assert "HOLD" in html
        assert "SELL" in html

    def test_signal_counts_in_header(self):
        stocks = [_make_stock("BUY"), _make_stock("BUY"), _make_stock("SELL")]
        html = format_email_html(stocks, date(2024, 4, 26))
        assert "2 BUY" in html
        assert "1 SELL" in html

    def test_returns_valid_html_skeleton(self):
        html = format_email_html([_make_stock()], date(2024, 4, 26))
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_no_beta_omits_beta_line(self):
        stock = _make_stock("BUY")
        stock["beta"] = None
        html = format_email_html([stock], date(2024, 4, 26))
        assert "Beta" not in html


class TestFormatMorningEmailHtml:
    def test_html_contains_date(self):
        html = format_morning_email_html([_make_morning_note()], date(2024, 4, 27))
        assert "27 Apr 2024" in html

    def test_intact_group_present(self):
        html = format_morning_email_html([_make_morning_note("INTACT")], date(2024, 4, 27))
        assert "INTACT" in html

    def test_mixed_statuses_all_groups_rendered(self):
        notes = [
            _make_morning_note("INTACT", "BUY"),
            _make_morning_note("STRENGTHENED", "BUY"),
            _make_morning_note("WEAKENED", "SELL"),
        ]
        html = format_morning_email_html(notes, date(2024, 4, 27))
        assert "STRENGTHENED" in html
        assert "WEAKENED" in html

    def test_counts_in_header(self):
        notes = [_make_morning_note("INTACT"), _make_morning_note("INTACT")]
        html = format_morning_email_html(notes, date(2024, 4, 27))
        assert "2" in html

    def test_empty_group_omitted(self):
        html = format_morning_email_html([_make_morning_note("INTACT")], date(2024, 4, 27))
        assert "STRENGTHENED (0)" not in html

    def test_returns_valid_html_skeleton(self):
        html = format_morning_email_html([_make_morning_note()], date(2024, 4, 27))
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
