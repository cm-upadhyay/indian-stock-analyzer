"""MCP tool: get_peer_comparison — sector PE/PB and peer relative performance.

A NEW data tool (Task 3.4). Requested by the LLM when it needs to know
whether a stock is cheap/expensive relative to its sector peers.

Data source: yfinance (sector ETF price return as sector proxy, peer list from
ticker.info's sector field to build a small peer set).
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()

# Sector → representative ETF or index (NSE sector indices via yfinance)
_SECTOR_ETFS = {
    "Technology": "^CNXIT",  # Nifty IT
    "Financial Services": "^CNXFIN",  # Nifty Financial Services
    "Energy": "^CNXENERGY",
    "Consumer Defensive": "^CNXFMCG",
    "Healthcare": "^CNXPHARMA",
    "Industrials": "^CNXINFRA",
    "Basic Materials": "^CNXMETAL",
    "Utilities": "^CNXAUTO",  # closest proxy
    "Real Estate": "^CNXREALTY",
}

# Known peer groups by sector (top 5 by liquidity) — bootstrapped list
_PEER_GROUPS: dict[str, list[str]] = {
    "Technology": ["TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS"],
    "Financial Services": ["HDFCBANK.NS", "ICICIBANK.NS", "KOTAKBANK.NS", "AXISBANK.NS", "SBIN.NS"],
    "Energy": ["RELIANCE.NS", "ONGC.NS", "IOC.NS", "BPCL.NS", "GAIL.NS"],
    "Consumer Defensive": ["HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "MARICO.NS", "DABUR.NS"],
    "Healthcare": ["SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS", "TORNTPHARM.NS"],
}


def run(symbol: str) -> dict:  # type: ignore[type-arg]
    """Compare a stock to sector peers. Returns relative valuation and returns."""
    ns_symbol = f"{symbol}.NS"
    try:
        import yfinance as yf

        ticker = yf.Ticker(ns_symbol)
        info = ticker.info or {}

        sector = info.get("sector", "Unknown")
        trailing_pe = info.get("trailingPE")
        price_to_book = info.get("priceToBook")

        # 1-month return for this stock
        hist = ticker.history(period="1mo")
        stock_return_1m: float | None = None
        if hist is not None and len(hist) >= 2:
            stock_return_1m = round(
                (hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0] * 100, 2
            )

        # Sector 1-month return (using ETF proxy)
        sector_etf = _SECTOR_ETFS.get(sector)
        sector_return_1m: float | None = None
        if sector_etf:
            try:
                etf_hist = yf.Ticker(sector_etf).history(period="1mo")
                if etf_hist is not None and len(etf_hist) >= 2:
                    sector_return_1m = round(
                        (etf_hist["Close"].iloc[-1] - etf_hist["Close"].iloc[0])
                        / etf_hist["Close"].iloc[0]
                        * 100,
                        2,
                    )
            except Exception:
                pass

        # Peer PE/PB comparison
        peers = _PEER_GROUPS.get(sector, [])
        peer_pes: list[float] = []
        peer_pbs: list[float] = []
        for peer_sym in peers:
            if peer_sym == ns_symbol:
                continue
            try:
                peer_info = yf.Ticker(peer_sym).info or {}
                if pe := peer_info.get("trailingPE"):
                    peer_pes.append(float(pe))
                if pb := peer_info.get("priceToBook"):
                    peer_pbs.append(float(pb))
            except Exception:
                continue

        sector_median_pe = round(sorted(peer_pes)[len(peer_pes) // 2], 1) if peer_pes else None
        sector_median_pb = round(sorted(peer_pbs)[len(peer_pbs) // 2], 1) if peer_pbs else None

        pe_vs_sector = (
            "cheaper than sector"
            if trailing_pe and sector_median_pe and trailing_pe < sector_median_pe
            else "expensive vs sector"
            if trailing_pe and sector_median_pe and trailing_pe > sector_median_pe * 1.2
            else "in line with sector"
        )

        return {
            "symbol": symbol,
            "sector": sector,
            "stock_pe": round(trailing_pe, 1) if trailing_pe else None,
            "stock_pb": round(price_to_book, 2) if price_to_book else None,
            "sector_median_pe": sector_median_pe,
            "sector_median_pb": sector_median_pb,
            "pe_vs_sector": pe_vs_sector,
            "stock_return_1m_pct": stock_return_1m,
            "sector_return_1m_pct": sector_return_1m,
            "peers_used": peers[:5],
            "error": None,
        }
    except Exception as e:
        log.error("mcp_peers_failed", symbol=symbol, error=str(e))
        return {"symbol": symbol, "error": str(e)}
