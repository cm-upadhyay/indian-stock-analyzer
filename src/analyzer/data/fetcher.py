"""Fetch raw stock data and delivery % — assembles StockData and DeliveryData models."""

from __future__ import annotations

import pandas as pd
import structlog

from analyzer.adapters import nse as nse_adapter
from analyzer.adapters import yfinance as yf_adapter
from analyzer.data.models import DeliveryData, StockData

log = structlog.get_logger()


def _company_name(symbol: str, info: dict) -> str:  # type: ignore[type-arg]
    return info.get("longName") or info.get("shortName") or symbol.replace(".NS", "")


def fetch_stock_data(symbol: str) -> StockData:
    log.info("fetch_stock_data", symbol=symbol)
    ohlcv = yf_adapter.get_ohlcv(symbol, period="1y")
    if ohlcv.empty:
        raise ValueError(f"No data returned for {symbol} — check the symbol")

    close = ohlcv["Close"]
    current_price = float(close.iloc[-1])
    high_52w = float(close.max())
    low_52w = float(close.min())
    pct_from_low = (current_price - low_52w) / (high_52w - low_52w) * 100

    info = yf_adapter.get_ticker_info(symbol)

    cashflow: pd.DataFrame | None = None
    balance_sheet: pd.DataFrame | None = None
    financials: pd.DataFrame | None = None

    # Pre-fetch statements — needed for NSE stocks where ticker.info is incomplete
    cf = yf_adapter.get_cashflow(symbol)
    if not cf.empty:
        cashflow = cf

    bs = yf_adapter.get_balance_sheet(symbol)
    if not bs.empty:
        balance_sheet = bs

    fin = yf_adapter.get_financials(symbol)
    if not fin.empty:
        financials = fin

    recommendations = yf_adapter.get_recommendations(symbol)

    return StockData(
        symbol=symbol,
        company_name=_company_name(symbol, info),
        ohlcv=ohlcv,
        current_price=current_price,
        high_52w=high_52w,
        low_52w=low_52w,
        pct_from_low=pct_from_low,
        info=info,
        cashflow=cashflow,
        balance_sheet=balance_sheet,
        financials=financials,
        recommendations=recommendations,
    )


def fetch_delivery_data(symbol: str, current_price: float, prev_price: float) -> DeliveryData:
    """Fetch NSE delivery % and derive BUY/NEUTRAL/SELL signal."""
    log.info("fetch_delivery_data", symbol=symbol)
    nse_sym = symbol.replace(".NS", "")
    dp = nse_adapter.get_delivery_data(nse_sym)

    delivery_pct: float | None = None
    delivery_date: str | None = None

    if dp:
        delivery_pct = dp.get("deliveryToTradedQuantity")
        delivery_date = dp.get("secWiseDelPosDate", "previous day")

    if delivery_pct is None:
        return DeliveryData(
            delivery_pct=None,
            delivery_date=None,
            signal="NEUTRAL",
            label="unavailable",
        )

    today_return = (current_price - prev_price) / prev_price * 100

    if delivery_pct > 60:
        signal = "BUY" if today_return >= 0 else "SELL"
        label = f"{delivery_pct:.0f}% — conviction {'buying' if today_return >= 0 else 'selling'}"
    elif delivery_pct < 30:
        signal = "NEUTRAL"
        label = f"{delivery_pct:.0f}% — speculative, low conviction"
    else:
        signal = "BUY" if today_return > 0.5 else "SELL" if today_return < -0.5 else "NEUTRAL"
        label = f"{delivery_pct:.0f}% — normal"

    return DeliveryData(
        delivery_pct=delivery_pct,
        delivery_date=delivery_date,
        signal=signal,
        label=label,
    )
