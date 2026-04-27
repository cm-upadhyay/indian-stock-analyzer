"""Tests for morning.py — _extract_status and news parsing logic."""

from __future__ import annotations

from analyzer.data.models import NewsItem
from analyzer.data.news import fetch_news, format_news_context
from analyzer.llm.morning import _extract_status

# ── _extract_status ────────────────────────────────────────────────────────────


def test_extract_status_intact_exact():
    assert _extract_status("Signal INTACT — no change") == "INTACT"


def test_extract_status_strengthened_exact():
    assert _extract_status("Signal STRENGTHENED since last night") == "STRENGTHENED"


def test_extract_status_weakened_exact():
    assert _extract_status("Signal WEAKENED due to US selloff") == "WEAKENED"


def test_extract_status_case_insensitive_lower():
    # LLMs sometimes return lowercase — must not default to INTACT incorrectly
    assert _extract_status("signal strengthened overnight") == "STRENGTHENED"


def test_extract_status_case_insensitive_mixed():
    assert _extract_status("Signal Weakened given the Nikkei drop") == "WEAKENED"


def test_extract_status_defaults_intact_when_not_found():
    # If LLM writes something unexpected, default is INTACT
    assert _extract_status("No clear status mentioned here.") == "INTACT"


def test_extract_status_intact_takes_first_match():
    # Only one should match in normal output — this just confirms no crash with multiple
    result = _extract_status("Signal INTACT. Signal INTACT again.")
    assert result == "INTACT"


# ── fetch_news / format_news_context ──────────────────────────────────────────


def _make_raw_news(title: str, summary: str = "", publisher: str = "Test") -> dict:
    """Build a yfinance-style news item (new format with nested 'content')."""
    return {
        "content": {
            "title": title,
            "summary": summary,
            "provider": {"displayName": publisher},
        }
    }


def _make_legacy_news(title: str, summary: str = "", publisher: str = "Test") -> dict:
    """Build a yfinance-style news item (old flat format)."""
    return {"title": title, "description": summary, "publisher": publisher}


def test_fetch_news_uses_nested_content_format(monkeypatch):
    raw = [_make_raw_news("Stock rises 5%", "Big move today", "ET Markets")]
    monkeypatch.setattr("analyzer.adapters.yfinance.get_news", lambda sym: raw)

    items = fetch_news("RELIANCE.NS")

    assert len(items) == 1
    assert items[0].title == "Stock rises 5%"
    assert items[0].publisher == "ET Markets"
    assert items[0].summary == "Big move today"


def test_fetch_news_falls_back_to_legacy_format(monkeypatch):
    raw = [_make_legacy_news("Stock falls 3%", "Weak session", "Moneycontrol")]
    monkeypatch.setattr("analyzer.adapters.yfinance.get_news", lambda sym: raw)

    items = fetch_news("TCS.NS")

    assert len(items) == 1
    assert items[0].title == "Stock falls 3%"
    assert items[0].publisher == "Moneycontrol"


def test_fetch_news_returns_placeholder_when_empty(monkeypatch):
    monkeypatch.setattr("analyzer.adapters.yfinance.get_news", lambda sym: [])

    items = fetch_news("INFY.NS")

    assert len(items) == 1
    assert items[0].title == "No recent news found"


def test_fetch_news_skips_items_without_title(monkeypatch):
    raw = [{"content": {"summary": "no title here", "provider": {"displayName": "X"}}}]
    monkeypatch.setattr("analyzer.adapters.yfinance.get_news", lambda sym: raw)

    items = fetch_news("WIPRO.NS")

    # Should return placeholder since no valid titles
    assert items[0].title == "No recent news found"


def test_fetch_news_respects_max_items(monkeypatch):
    raw = [_make_raw_news(f"Headline {i}") for i in range(6)]
    monkeypatch.setattr("analyzer.adapters.yfinance.get_news", lambda sym: raw)

    items = fetch_news("HDFCBANK.NS", max_items=2)

    assert len(items) == 2


def test_fetch_news_truncates_long_summaries(monkeypatch):
    long_summary = "x" * 500
    raw = [_make_raw_news("Title", long_summary)]
    monkeypatch.setattr("analyzer.adapters.yfinance.get_news", lambda sym: raw)

    items = fetch_news("AXISBANK.NS")

    assert len(items[0].summary) <= 200


def test_format_news_context_includes_publisher_and_title():
    items = [NewsItem(title="Big rally", summary="Up 5%", publisher="ET Markets")]
    ctx = format_news_context(items)

    assert "[ET Markets]" in ctx
    assert "Big rally" in ctx
    assert "Up 5%" in ctx


def test_format_news_context_omits_empty_summary():
    items = [NewsItem(title="Short note", summary="", publisher="Reuters")]
    ctx = format_news_context(items)

    assert "Short note" in ctx
    # No trailing newline for empty summary section
    assert "\n  " not in ctx
