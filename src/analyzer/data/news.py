"""Fetch and format stock news via yfinance."""

from __future__ import annotations

import re

import structlog

from analyzer.adapters import yfinance as yf_adapter
from analyzer.data.models import NewsItem

log = structlog.get_logger()

# Characters that could be used for prompt injection — strip them from external news content
_INJECTION_PATTERN = re.compile(
    r"[<>{}\[\]\\]|ignore\s+all|forget\s+previous|system\s*:", re.IGNORECASE
)


def _sanitize(text: str, max_len: int) -> str:
    """Remove prompt-injection patterns and control characters from external text."""
    cleaned = _INJECTION_PATTERN.sub("", text)
    cleaned = "".join(c for c in cleaned if c.isprintable())
    return cleaned[:max_len].strip()


def fetch_news(symbol: str, max_items: int = 3) -> list[NewsItem]:
    log.info("fetch_news", symbol=symbol)
    raw = yf_adapter.get_news(symbol)
    items: list[NewsItem] = []

    for item in raw[:6]:
        content = item.get("content", {})
        title = item.get("title") or content.get("title", "")
        summary = content.get("summary", "") or item.get("description", "")
        publisher = content.get("provider", {}).get("displayName", "") or item.get("publisher", "")
        if title:
            items.append(
                NewsItem(
                    title=_sanitize(title, 200),
                    summary=_sanitize(summary, 200),
                    publisher=_sanitize(publisher, 80),
                )
            )

    return items[:max_items] or [NewsItem(title="No recent news found", summary="", publisher="")]


def format_news_context(items: list[NewsItem]) -> str:
    return "\n".join(
        f"- [{item.publisher}] {item.title}" + (f"\n  {item.summary}" if item.summary else "")
        for item in items
    )
