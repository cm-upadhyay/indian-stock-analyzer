"""Fetch and format stock news via yfinance."""

from __future__ import annotations

import re
import time
from datetime import datetime

import structlog

from analyzer.adapters import yfinance as yf_adapter
from analyzer.config import settings
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


def _age_label(publish_ts: int | None) -> str:
    """Return a human-readable age prefix like '[3 days ago]' or '[2 months ago]'.

    Prepended to article titles so the LLM can reason about recency without needing
    to parse dates. An article labelled '[5 months ago]' about earnings will not
    cause the LLM to call get_corporate_actions() thinking the event is upcoming.
    Returns empty string for articles published within the last 2 days (fresh enough
    that no label is needed).
    """
    if not publish_ts:
        return "[date unknown] "
    age_days = (time.time() - publish_ts) / 86400
    if age_days <= settings.news_fresh_days:
        return ""
    if age_days <= 14:
        return f"[{int(age_days)} days ago] "
    if age_days <= 60:
        return f"[{int(age_days // 7)} weeks ago] "
    months = int(age_days // 30)
    return f"[{months} month{'s' if months > 1 else ''} ago] "


def fetch_news(symbol: str, max_items: int = 3) -> list[NewsItem]:
    log.info("fetch_news", symbol=symbol)
    raw = yf_adapter.get_news(symbol)
    items: list[NewsItem] = []
    now = time.time()

    for item in raw[:10]:  # scan more to allow for staleness filtering
        content = item.get("content", {})
        title = item.get("title") or content.get("title", "")
        summary = content.get("summary", "") or item.get("description", "")
        publisher = content.get("provider", {}).get("displayName", "") or item.get("publisher", "")

        publish_ts = item.get("providerPublishTime") or content.get("pubDate")
        # Normalise pubDate string → Unix timestamp if needed
        if isinstance(publish_ts, str):
            try:
                publish_ts = int(
                    datetime.fromisoformat(publish_ts.replace("Z", "+00:00")).timestamp()
                )
            except Exception:
                publish_ts = None

        # Drop articles older than _MAX_AGE_DAYS — too stale to influence today's verdict
        if publish_ts and (now - publish_ts) / 86400 > settings.news_max_age_days:
            log.info(
                "news_dropped_stale",
                symbol=symbol,
                title=title[:60],
                age_days=int((now - publish_ts) / 86400),
            )
            continue

        if title:
            age_prefix = _age_label(publish_ts)
            items.append(
                NewsItem(
                    title=_sanitize(age_prefix + title, 220),
                    summary=_sanitize(summary, 200),
                    publisher=_sanitize(publisher, 80),
                )
            )

        if len(items) == max_items:
            break

    return items or [NewsItem(title="No recent news found", summary="", publisher="")]


def format_news_context(items: list[NewsItem]) -> str:
    return "\n".join(
        f"- [{item.publisher}] {item.title}" + (f"\n  {item.summary}" if item.summary else "")
        for item in items
    )
