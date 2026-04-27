"""Market screener — fetches live Nifty 500 constituents, shortlists 30 candidates.

Universe:    NSE archives Nifty 500 CSV (refreshed daily by NSE, no auth required).
Scoring:     3-signal technical pass — RSI + MA20 + MA50. Zero LLM cost.
Diversification:
  - Sector cap: max 3 stocks per NSE industry (20 sectors in Nifty 500).
  - Volume floor: symbols with avg daily volume < MIN_AVG_VOLUME are skipped.
  - Tie-breaking: equal-score stocks ranked by avg volume (more liquid preferred).
Output:      top 30 after sector cap applied.

Falls back to a minimal hardcoded list if the NSE CSV is unreachable.
"""

from __future__ import annotations

import time
from io import StringIO

import pandas as pd
import requests
import structlog

from analyzer.adapters import yfinance as yf_adapter

log = structlog.get_logger()

_NIFTY500_CSV = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
_CHUNK_SIZE = 50
_CHUNK_SLEEP = 2.0
_MAX_PICKS = 30
_MAX_PER_SECTOR = 3
_MIN_AVG_VOLUME = 200_000  # avg daily shares — filters genuinely illiquid names

_FALLBACK_SYMBOLS = [
    "RELIANCE.NS",
    "TCS.NS",
    "HDFCBANK.NS",
    "INFY.NS",
    "ICICIBANK.NS",
    "KOTAKBANK.NS",
    "HINDUNILVR.NS",
    "AXISBANK.NS",
    "SBIN.NS",
    "BHARTIARTL.NS",
    "ITC.NS",
    "ASIANPAINT.NS",
    "MARUTI.NS",
    "BAJFINANCE.NS",
    "HCLTECH.NS",
    "WIPRO.NS",
    "ONGC.NS",
    "TATAMOTORS.NS",
    "SUNPHARMA.NS",
    "NESTLEIND.NS",
]


def _fetch_universe() -> tuple[list[str], dict[str, str]]:
    """Fetch Nifty 500 from NSE archives.

    Returns (symbols, sector_map) where sector_map is {symbol → industry}.
    Falls back to hardcoded list with empty sector_map on error.
    """
    try:
        resp = requests.get(
            _NIFTY500_CSV,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
        symbols = [f"{s.strip()}.NS" for s in df["Symbol"].dropna()]
        sector_map = {
            f"{row['Symbol'].strip()}.NS": row["Industry"]
            for _, row in df.iterrows()
            if pd.notna(row["Industry"])
        }
        log.info("nifty500_fetched", count=len(symbols), sectors=len(set(sector_map.values())))
        return symbols, sector_map
    except Exception as e:
        log.warning("nifty500_fetch_failed", error=str(e), fallback=len(_FALLBACK_SYMBOLS))
        return _FALLBACK_SYMBOLS, {}


def _score_symbol(symbol: str, raw: pd.DataFrame) -> tuple[float, float] | None:
    """Return (technical_score, avg_volume) or None if symbol fails quality filters.

    Score 0–4:
      +2  RSI < 35 (oversold — mean-reversion candidate)
      +1  RSI > 65 (momentum)
      +1  price > MA50 (above medium-term trend)
      +1  MA20 > MA50 (golden cross territory)

    avg_volume is used as a tie-breaker — higher volume preferred at equal score.
    """
    try:
        close = raw[symbol]["Close"].dropna() if symbol in raw.columns else raw["Close"].dropna()
        volume = raw[symbol]["Volume"].dropna() if symbol in raw.columns else raw["Volume"].dropna()

        if len(close) < 50:
            return None

        avg_vol = float(volume.mean())
        if avg_vol < _MIN_AVG_VOLUME:
            return None

        import ta as _ta

        rsi = float(_ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1])
        ma20 = float(_ta.trend.SMAIndicator(close, window=20).sma_indicator().iloc[-1])
        ma50 = float(_ta.trend.SMAIndicator(close, window=50).sma_indicator().iloc[-1])
        current = float(close.iloc[-1])

        score = 0.0
        if rsi < 35:
            score += 2
        elif rsi > 65:
            score += 1
        if current > ma50:
            score += 1
        if ma20 > ma50:
            score += 1

        return score, avg_vol
    except Exception:
        return None


def run_screener(symbols: list[str] | None = None) -> list[str]:
    """Return up to 30 candidate symbols for the 4 PM pipeline.

    Pass ``symbols`` to override the live Nifty 500 fetch (useful in tests).
    Sector cap is skipped when symbols are passed manually (no sector info available).
    """
    sector_map: dict[str, str]
    if symbols:
        universe, sector_map = symbols, {}
    else:
        universe, sector_map = _fetch_universe()

    log.info("screener_start", universe=len(universe))

    # ── Score every symbol ────────────────────────────────────────────────────
    # Each entry: (score, avg_volume, symbol)
    scored: list[tuple[float, float, str]] = []
    chunks = [universe[i : i + _CHUNK_SIZE] for i in range(0, len(universe), _CHUNK_SIZE)]

    for i, chunk in enumerate(chunks):
        if i > 0:
            time.sleep(_CHUNK_SLEEP)
        log.info("screener_chunk", chunk=i + 1, total=len(chunks), scored_so_far=len(scored))
        raw = yf_adapter.get_batch_download(chunk)
        if raw.empty:
            continue
        for sym in chunk:
            result = _score_symbol(sym, raw)
            if result is not None:
                score, avg_vol = result
                scored.append((score, avg_vol, sym))

    # ── Rank: primary = score desc, secondary = volume desc ───────────────────
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

    # ── Sector-capped greedy selection ────────────────────────────────────────
    sector_counts: dict[str, int] = {}
    picks: list[str] = []

    for *_, sym in scored:
        sector = sector_map.get(sym, "Unknown")
        if sector_counts.get(sector, 0) < _MAX_PER_SECTOR:
            picks.append(sym)
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
        if len(picks) >= _MAX_PICKS:
            break

    log.info(
        "screener_done",
        selected=len(picks),
        sectors_represented=len(sector_counts),
        sector_breakdown=dict(sorted(sector_counts.items())),
    )
    return picks
