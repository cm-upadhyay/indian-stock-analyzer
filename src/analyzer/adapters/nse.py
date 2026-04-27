"""All NSE HTTP calls live here — nowhere else in the codebase.

NSE requires session warm-up (cookie fetch from the homepage) before every API call.
Sessions expire quickly; always call _warm() before any endpoint.
"""

from __future__ import annotations

from typing import Any, cast

import requests
import structlog

from analyzer.utils.reliability import nse_breaker, retry_api

log = structlog.get_logger()

_BASE = "https://www.nseindia.com"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": f"{_BASE}/",
}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_HEADERS)
    return s


def _warm(session: requests.Session) -> None:
    """Fetch NSE homepage to get session cookies. Must be called before every API call."""
    session.get(f"{_BASE}/", timeout=10)


def _nse_get(
    url: str, params: dict[str, str] | None = None, timeout: int = 10
) -> requests.Response:
    """Single NSE HTTP GET with fresh session — raises on failure so breaker sees it."""

    def _call() -> requests.Response:
        session = _session()
        _warm(session)
        resp = session.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp

    return cast("requests.Response", nse_breaker(retry_api(_call))())


def get_delivery_data(symbol: str) -> dict[str, object] | None:
    """Fetch delivery % (securityWiseDP) for a stock symbol (without .NS suffix)."""
    try:
        resp = _nse_get(f"{_BASE}/api/quote-equity", {"symbol": symbol, "section": "trade_info"})
        payload: Any = resp.json()
        if isinstance(payload, dict):
            security = payload.get("securityWiseDP")
            return security if isinstance(security, dict) else None
    except Exception as e:
        log.warning("nse_delivery_failed", symbol=symbol, error=str(e))
    return None


def get_option_chain_equity(symbol: str) -> list[dict[str, object]]:
    """Fetch option chain data for a stock (equity segment)."""
    try:
        resp = _nse_get(f"{_BASE}/api/option-chain-equities", {"symbol": symbol}, timeout=15)
        payload: Any = resp.json()
        if isinstance(payload, dict):
            records = payload.get("records")
            if isinstance(records, dict):
                data = records.get("data")
                if isinstance(data, list):
                    return [item for item in data if isinstance(item, dict)]
    except Exception as e:
        log.warning("nse_option_chain_failed", symbol=symbol, error=str(e))
    return []


def get_pledge_data(symbol: str) -> list[dict[str, object]]:
    """Fetch promoter pledge data for a stock."""
    try:
        resp = _nse_get(
            f"{_BASE}/api/corporate-pledgedata", {"index": "equities", "symbol": symbol}
        )
        data: Any = resp.json()
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            nested = data.get("data")
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    except Exception as e:
        log.warning("nse_pledge_failed", symbol=symbol, error=str(e))
    return []


def get_fii_dii_flows() -> list[dict[str, object]]:
    """Fetch today's provisional FII/DII net flows."""
    try:
        data: Any = _nse_get(f"{_BASE}/api/fiidiiTradeReact").json()
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except Exception as e:
        log.warning("nse_fii_dii_failed", error=str(e))
    return []


def get_nifty_option_chain() -> list[dict[str, object]]:
    """Fetch Nifty index option chain (for market-wide PCR)."""
    try:
        resp = _nse_get(f"{_BASE}/api/option-chain-indices", {"symbol": "NIFTY"}, timeout=15)
        payload: Any = resp.json()
        if isinstance(payload, dict):
            records = payload.get("records")
            if isinstance(records, dict):
                data = records.get("data")
                if isinstance(data, list):
                    return [item for item in data if isinstance(item, dict)]
    except Exception as e:
        log.warning("nse_nifty_chain_failed", error=str(e))
    return []
