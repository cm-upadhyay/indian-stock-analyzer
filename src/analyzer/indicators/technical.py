"""12 technical indicator votes — pure computation, zero external calls.

Input: OHLCV DataFrame + delivery signal from DeliveryData.
Output: TechnicalSignals with votes dict and raw values for display.
"""

from __future__ import annotations

import pandas as pd
import ta

from analyzer.data.models import TechnicalSignals


def compute_technical(
    ohlcv: pd.DataFrame,
    current_price: float,
    high_52w: float,
    low_52w: float,
    pct_from_low: float,
    delivery_signal: str,
    delivery_label: str,
) -> TechnicalSignals:
    close = ohlcv["Close"]
    volume = ohlcv["Volume"]
    high = ohlcv["High"]
    low = ohlcv["Low"]

    # ── Core trend & momentum ─────────────────────────────────────────────────
    rsi = float(ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1])
    ma20 = float(ta.trend.SMAIndicator(close, window=20).sma_indicator().iloc[-1])
    ma50 = float(ta.trend.SMAIndicator(close, window=50).sma_indicator().iloc[-1])
    ma200 = float(ta.trend.SMAIndicator(close, window=200).sma_indicator().iloc[-1])

    macd_ind = ta.trend.MACD(close)
    macd_bullish = bool(macd_ind.macd().iloc[-1] > macd_ind.macd_signal().iloc[-1])

    avg_vol_20 = float(volume.rolling(20).mean().iloc[-1])
    volume_ratio = float(volume.iloc[-1] / avg_vol_20)
    macd_reliable = volume_ratio >= 0.5

    # ── Additional oscillators ────────────────────────────────────────────────
    stoch = ta.momentum.StochasticOscillator(high, low, close)
    stoch_k = float(stoch.stoch().iloc[-1])
    stoch_d = float(stoch.stoch_signal().iloc[-1])

    bb = ta.volatility.BollingerBands(close)
    bb_upper = float(bb.bollinger_hband().iloc[-1])
    bb_lower = float(bb.bollinger_lband().iloc[-1])
    bb_pct = (current_price - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5

    williams_r = float(ta.momentum.WilliamsRIndicator(high, low, close).williams_r().iloc[-1])
    cci = float(ta.trend.CCIIndicator(high, low, close).cci().iloc[-1])

    # ── Plain-English labels ──────────────────────────────────────────────────
    rsi_label = (
        "overbought — may pull back"
        if rsi > 70
        else "oversold — potential bounce"
        if rsi < 30
        else "neutral"
    )
    trend_ma200 = (
        "long-term uptrend — institutions likely buying"
        if current_price > ma200
        else "long-term downtrend — many funds avoiding"
    )
    macd_direction = "bullish crossover" if macd_bullish else "bearish crossover"
    macd_label = macd_direction + (
        "" if macd_reliable else " — LOW CONVICTION (volume too low, dismiss this signal)"
    )
    vol_label = (
        "unusually high — confirms price moves"
        if volume_ratio > 1.5
        else "unusually low — low conviction"
        if volume_ratio < 0.5
        else "normal"
    )
    w52_label = (
        f"{abs((current_price - high_52w) / high_52w * 100):.1f}% below 52w high"
        if current_price < high_52w * 0.99
        else "near 52-week high — strong demand zone"
    )

    # ── Votes ─────────────────────────────────────────────────────────────────
    votes: dict[str, str] = {
        "RSI": "BUY" if rsi < 30 else "SELL" if rsi > 70 else "NEUTRAL",
        "Price_vs_MA50": "BUY" if current_price > ma50 else "SELL",
        "Price_vs_MA200": "BUY" if current_price > ma200 else "SELL",
        "MA20_vs_MA50": "BUY" if ma20 > ma50 else "SELL",
        "MACD": ("BUY" if macd_bullish else "SELL") if macd_reliable else "NEUTRAL",
        "Delivery_Pct": delivery_signal,
        "Stoch_K_Level": "BUY" if stoch_k < 20 else "SELL" if stoch_k > 80 else "NEUTRAL",
        "Stoch_Signal": "BUY" if stoch_k > stoch_d else "SELL",
        "Bollinger": "BUY" if bb_pct < 0.2 else "SELL" if bb_pct > 0.8 else "NEUTRAL",
        "Williams_R": "BUY" if williams_r < -80 else "SELL" if williams_r > -20 else "NEUTRAL",
        "CCI": "BUY" if cci < -100 else "SELL" if cci > 100 else "NEUTRAL",
        "52w_Position": "BUY" if pct_from_low > 75 else "SELL" if pct_from_low < 25 else "NEUTRAL",
    }

    return TechnicalSignals(
        votes=votes,
        rsi=rsi,
        ma20=ma20,
        ma50=ma50,
        ma200=ma200,
        macd_bullish=macd_bullish,
        macd_reliable=macd_reliable,
        volume_ratio=volume_ratio,
        stoch_k=stoch_k,
        stoch_d=stoch_d,
        bb_pct=bb_pct,
        williams_r=williams_r,
        cci=cci,
        pct_from_low=pct_from_low,
        delivery_signal=delivery_signal,
        delivery_label=delivery_label,
        rsi_label=rsi_label,
        trend_ma200=trend_ma200,
        macd_label=macd_label,
        vol_label=vol_label,
        w52_label=w52_label,
    )
