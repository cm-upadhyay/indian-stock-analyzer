"""MCP tool: get_technical_signals — exposes the existing technical pipeline as a tool.

This wraps the existing Phase 2 modules (adapters, data, indicators) and returns
a compact JSON summary suitable for LLM consumption.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()


def run(symbol: str) -> dict:  # type: ignore[type-arg]
    """Fetch OHLCV + compute all 12 technical signals. Returns a compact dict."""
    try:
        from analyzer.data.fetcher import fetch_delivery_data, fetch_stock_data
        from analyzer.indicators import technical as tech_module
        from analyzer.schemas.dataframes import validate_ohlcv

        stock = fetch_stock_data(symbol)

        # Validate DataFrame at the MCP boundary
        validate_ohlcv(stock.ohlcv, symbol)

        close = stock.ohlcv["Close"]
        prev_price = float(close.iloc[-2]) if len(close) >= 2 else stock.current_price
        delivery = fetch_delivery_data(symbol, stock.current_price, prev_price)

        tech = tech_module.compute_technical(
            ohlcv=stock.ohlcv,
            current_price=stock.current_price,
            high_52w=stock.high_52w,
            low_52w=stock.low_52w,
            pct_from_low=stock.pct_from_low,
            delivery_signal=delivery.signal,
            delivery_label=delivery.label,
        )

        buy_count = sum(1 for v in tech.votes.values() if v == "BUY")
        sell_count = sum(1 for v in tech.votes.values() if v == "SELL")
        neutral_count = len(tech.votes) - buy_count - sell_count

        return {
            "symbol": symbol,
            "current_price": stock.current_price,
            "votes": {"buy": buy_count, "neutral": neutral_count, "sell": sell_count},
            "rsi": round(tech.rsi, 1),
            "rsi_label": tech.rsi_label,
            "ma_trend": tech.trend_ma200,
            "macd": tech.macd_label,
            "volume_ratio": round(tech.volume_ratio, 2),
            "52w_position_pct": round(tech.pct_from_low, 1),
            "stoch_k": round(tech.stoch_k, 1),
            "stoch_d": round(tech.stoch_d, 1),
            "bollinger_pct": round(tech.bb_pct, 2),
            "delivery": tech.delivery_label,
            "error": None,
        }
    except Exception as e:
        log.error("mcp_technical_failed", symbol=symbol, error=str(e))
        return {"symbol": symbol, "error": str(e)}
