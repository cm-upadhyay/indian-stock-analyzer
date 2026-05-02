"""Macro-news tool — broad Indian market themes via Tavily search.

Why Tavily instead of yfinance for macro?
    yfinance gives stock-specific news. Tavily gives broad market news:
    RBI policy, FII flows, Union Budget, Nifty sector rotation, global cues.
    The agentic loop calls this when it needs context beyond a single stock.

Graceful degradation:
    If TAVILY_API_KEY is absent or Tavily fails, returns an empty list.
    The pipeline continues without macro context — it's an enhancement.

Cost:
    Tavily free tier = 1,000 searches/month.
    At 1 call per agentic run × 30 stocks/day = ~900 calls/month — fits free tier.
"""

from __future__ import annotations

import os

import structlog

log = structlog.get_logger()

_DEFAULT_QUERIES = [
    "India stock market today Nifty Sensex",
    "RBI monetary policy FII DII flows India",
    "Indian economy news today",
]


def run(query: str = "", max_results: int = 5) -> dict:  # type: ignore[type-arg]
    """Search for broad Indian market news using Tavily.

    Args:
        query:       search query — defaults to a broad Nifty/market query
        max_results: how many results to return (Tavily max = 10)

    Returns:
        {"results": [{"title": str, "url": str, "content": str}], "query": str}
        Returns {"results": [], "query": query} on any failure.
    """
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        log.warning("tavily_api_key_missing", hint="Set TAVILY_API_KEY to enable macro news")
        return {"results": [], "query": query}

    effective_query = query.strip() or _DEFAULT_QUERIES[0]

    try:
        from tavily import TavilyClient  # type: ignore[import-untyped]

        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=effective_query,
            max_results=max_results,
            search_depth="basic",
            include_domains=[
                "economictimes.indiatimes.com",
                "moneycontrol.com",
                "livemint.com",
                "business-standard.com",
                "ndtv.com",
                "financialexpress.com",
                "reuters.com",
                "bloomberg.com",
            ],
        )

        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "")[:300],  # cap per-result to keep tokens low
            }
            for r in response.get("results", [])
        ]
        log.info("macro_news_fetched", query=effective_query, count=len(results))
        return {"results": results, "query": effective_query}

    except ImportError:
        log.warning("tavily_not_installed", hint="pip install tavily-python")
        return {"results": [], "query": effective_query}
    except Exception as e:
        log.warning("macro_news_failed", query=effective_query, error=str(e))
        return {"results": [], "query": effective_query}
