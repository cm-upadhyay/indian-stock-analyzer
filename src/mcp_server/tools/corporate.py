"""MCP tool: get_corporate_actions — earnings, dividends, splits from yfinance.

A NEW data tool (Task 3.4). In Phase 2, corporate data was always fetched.
Now it's on-demand via MCP — the LLM requests it when it matters.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()


def run(symbol: str) -> dict:  # type: ignore[type-arg]
    """Fetch corporate events for a symbol (without .NS suffix)."""
    ns_symbol = f"{symbol}.NS"
    try:
        from datetime import date

        import yfinance as yf

        ticker = yf.Ticker(ns_symbol)

        # Earnings dates
        calendar = {}
        try:
            cal = ticker.calendar
            if cal is not None and not cal.empty:
                calendar = cal.to_dict()
        except Exception:
            pass

        # Dividend history (last 3)
        dividends: list[dict] = []
        try:
            div = ticker.dividends
            if div is not None and not div.empty:
                recent = div.tail(3)
                dividends = [
                    {"date": str(idx.date()), "amount": round(float(val), 2)}
                    for idx, val in zip(recent.index, recent.values, strict=False)
                ]
        except Exception:
            pass

        # Stock splits (last 2)
        splits: list[dict] = []
        try:
            sp = ticker.splits
            if sp is not None and not sp.empty:
                recent_splits = sp.tail(2)
                splits = [
                    {"date": str(idx.date()), "ratio": round(float(val), 2)}
                    for idx, val in zip(recent_splits.index, recent_splits.values, strict=False)
                ]
        except Exception:
            pass

        # Next earnings estimate
        next_earnings: str | None = None
        try:
            earnings_dates = ticker.earnings_dates
            if earnings_dates is not None and not earnings_dates.empty:
                future = earnings_dates[earnings_dates.index > str(date.today())]
                if not future.empty:
                    next_earnings = str(future.index[0].date())
        except Exception:
            pass

        return {
            "symbol": symbol,
            "next_earnings_date": next_earnings,
            "recent_dividends": dividends,
            "recent_splits": splits,
            "calendar": calendar,
            "error": None,
        }
    except Exception as e:
        log.error("mcp_corporate_failed", symbol=symbol, error=str(e))
        return {"symbol": symbol, "error": str(e)}
