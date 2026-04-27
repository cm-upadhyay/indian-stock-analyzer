"""All yfinance calls live here — nowhere else in the codebase."""

from __future__ import annotations

from typing import cast

import pandas as pd
import structlog
import yfinance as yf

from analyzer.utils.reliability import retry_api, yfinance_breaker

log = structlog.get_logger()


def get_batch_download(symbols: list[str], period: str = "60d") -> pd.DataFrame:
    """Download OHLCV for multiple symbols in one call — used by screener."""
    try:
        return yf.download(
            tickers=" ".join(symbols),
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        log.warning("yfinance_batch_download_failed", count=len(symbols), error=str(e))
        return pd.DataFrame()


def get_ohlcv(symbol: str, period: str = "1y") -> pd.DataFrame:
    # Critical path — no try/except so retry and circuit breaker see failures
    def _call() -> pd.DataFrame:
        return yf.Ticker(symbol).history(period=period)

    return yfinance_breaker(retry_api(_call))()


def get_ticker_info(symbol: str) -> dict[str, object]:
    # Critical path — no try/except so retry and circuit breaker see failures
    def _call() -> dict[str, object]:
        info = yf.Ticker(symbol).info
        return info if isinstance(info, dict) else {}

    info = yfinance_breaker(retry_api(_call))()
    return info if isinstance(info, dict) else {}


def get_cashflow(symbol: str) -> pd.DataFrame:
    try:
        return yf.Ticker(symbol).cashflow
    except Exception as e:
        log.warning("yfinance_cashflow_failed", symbol=symbol, error=str(e))
        return pd.DataFrame()


def get_balance_sheet(symbol: str) -> pd.DataFrame:
    try:
        return yf.Ticker(symbol).balance_sheet
    except Exception as e:
        log.warning("yfinance_balance_sheet_failed", symbol=symbol, error=str(e))
        return pd.DataFrame()


def get_financials(symbol: str) -> pd.DataFrame:
    try:
        return yf.Ticker(symbol).financials
    except Exception as e:
        log.warning("yfinance_financials_failed", symbol=symbol, error=str(e))
        return pd.DataFrame()


def get_news(symbol: str) -> list[dict[str, object]]:
    try:
        news = yf.Ticker(symbol).news
        return [item for item in news if isinstance(item, dict)] if isinstance(news, list) else []
    except Exception as e:
        log.warning("yfinance_news_failed", symbol=symbol, error=str(e))
        return []


def get_calendar(symbol: str) -> dict[str, object] | None:
    try:
        cal = yf.Ticker(symbol).calendar
        return cal if isinstance(cal, dict) and cal else None
    except Exception as e:
        log.warning("yfinance_calendar_failed", symbol=symbol, error=str(e))
        return None


def get_dividends(symbol: str) -> pd.Series[float]:
    try:
        return cast("pd.Series[float]", yf.Ticker(symbol).dividends)
    except Exception as e:
        log.warning("yfinance_dividends_failed", symbol=symbol, error=str(e))
        return cast("pd.Series[float]", pd.Series(dtype=float))


def get_actions(symbol: str) -> pd.DataFrame:
    try:
        return yf.Ticker(symbol).actions
    except Exception as e:
        log.warning("yfinance_actions_failed", symbol=symbol, error=str(e))
        return pd.DataFrame()


def get_recommendations(symbol: str) -> pd.DataFrame | None:
    try:
        recs = yf.Ticker(symbol).recommendations
        return recs if recs is not None and not recs.empty else None
    except Exception as e:
        log.warning("yfinance_recommendations_failed", symbol=symbol, error=str(e))
        return None


def get_price_history(symbol: str, period: str = "5d") -> pd.DataFrame:
    """Lightweight fetch for macro/global cues — just close prices."""
    try:
        h = yf.Ticker(symbol).history(period=period)
        return h if not h.empty else pd.DataFrame()
    except Exception as e:
        log.warning("yfinance_price_history_failed", symbol=symbol, error=str(e))
        return pd.DataFrame()
