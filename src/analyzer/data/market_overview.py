"""4 PM post-close India market context — Nifty, FII/DII, VIX, commodities."""

from __future__ import annotations

import pandas as pd
import structlog

from analyzer.adapters import nse as nse_adapter
from analyzer.adapters import yfinance as yf_adapter
from analyzer.data.models import MacroContext

log = structlog.get_logger()

_SECTOR_MAP: dict[str, tuple[str, str]] = {
    "RELIANCE.NS": ("^CNXEnergy", "Nifty Energy"),
    "TCS.NS": ("^CNXInfotech", "Nifty IT"),
    "HDFCBANK.NS": ("^NSEBANK", "Bank Nifty"),
    "INFY.NS": ("^CNXInfotech", "Nifty IT"),
    "WIPRO.NS": ("^CNXInfotech", "Nifty IT"),
    "ONGC.NS": ("^CNXEnergy", "Nifty Energy"),
    "TATAMOTORS.NS": ("^CNXAUTO", "Nifty Auto"),
    "MARUTI.NS": ("^CNXAUTO", "Nifty Auto"),
    "SUNPHARMA.NS": ("^CNXPHARMA", "Nifty Pharma"),
    "DRREDDY.NS": ("^CNXPHARMA", "Nifty Pharma"),
    "ICICIBANK.NS": ("^NSEBANK", "Bank Nifty"),
    "KOTAKBANK.NS": ("^NSEBANK", "Bank Nifty"),
    "AXISBANK.NS": ("^NSEBANK", "Bank Nifty"),
    "SBIN.NS": ("^NSEBANK", "Bank Nifty"),
}


def _last(h: pd.DataFrame) -> float | None:
    return float(h["Close"].iloc[-1]) if not h.empty else None


def _day_ret(h: pd.DataFrame) -> float | None:
    if len(h) >= 2:
        return float((h["Close"].iloc[-1] - h["Close"].iloc[-2]) / h["Close"].iloc[-2] * 100)
    return None


def _parse_fii_dii(flows: list[dict]) -> tuple[float | None, float | None]:  # type: ignore[type-arg]
    fii_net: float | None = None
    dii_net: float | None = None
    for item in flows:
        cat = str(item.get("category", "")).upper()
        for key in ["netValue", "net", "netTurnover", "net_value"]:
            if key in item and item[key] is not None:
                try:
                    val = float(str(item[key]).replace(",", ""))
                    if "FII" in cat or "FPI" in cat:
                        fii_net = val
                    elif "DII" in cat:
                        dii_net = val
                    break
                except ValueError:
                    pass
    return fii_net, dii_net


def _calc_pcr(oc_data: list[dict]) -> float | None:  # type: ignore[type-arg]
    if not oc_data:
        return None
    ce_oi = sum(r.get("CE", {}).get("openInterest", 0) for r in oc_data if "CE" in r)
    pe_oi = sum(r.get("PE", {}).get("openInterest", 0) for r in oc_data if "PE" in r)
    return pe_oi / ce_oi if ce_oi > 0 else None


def fetch_market_overview(symbol: str) -> MacroContext:
    log.info("fetch_market_overview", symbol=symbol)
    sector_sym, sector_name = _SECTOR_MAP.get(symbol, ("^NSEI", "Nifty 50"))

    vix_h = yf_adapter.get_price_history("^INDIAVIX")
    nifty_h = yf_adapter.get_price_history("^NSEI")
    sect_h = yf_adapter.get_price_history(sector_sym)
    brent_h = yf_adapter.get_price_history("BZ=F")
    gold_h = yf_adapter.get_price_history("GC=F")
    inr_h = yf_adapter.get_price_history("INR=X")

    india_vix = _last(vix_h)
    nifty_level = _last(nifty_h)
    nifty_return_pct = _day_ret(nifty_h)
    sector_return_pct = _day_ret(sect_h)
    brent_price = _last(brent_h)
    brent_ret_pct = _day_ret(brent_h)
    gold_price = _last(gold_h)
    usdinr = _last(inr_h)

    fii_flows = nse_adapter.get_fii_dii_flows()
    fii_net_cr, dii_net_cr = _parse_fii_dii(fii_flows)

    nifty_oc = nse_adapter.get_nifty_option_chain()
    nifty_pcr = _calc_pcr(nifty_oc)

    # Pre-format context block for the LLM prompt
    lines = []
    if nifty_return_pct is not None:
        lines.append(f"Nifty today: {nifty_return_pct:+.2f}%")
    if sector_return_pct is not None:
        lines.append(f"{sector_name}: {sector_return_pct:+.2f}%")
    if india_vix:
        lines.append(f"India VIX: {india_vix:.1f}")
    if fii_net_cr is not None:
        direction = "buying" if fii_net_cr >= 0 else "selling"
        lines.append(f"FII net: ₹{fii_net_cr:,.0f} Cr ({direction})")
    if dii_net_cr is not None:
        direction = "buying" if dii_net_cr >= 0 else "selling"
        lines.append(f"DII net: ₹{dii_net_cr:,.0f} Cr ({direction})")
    if nifty_pcr:
        lines.append(f"Nifty PCR: {nifty_pcr:.2f}")
    if brent_price:
        lines.append(f"Brent: ${brent_price:.1f}")
    if gold_price:
        lines.append(f"Gold: ${gold_price:,.0f}")
    if usdinr:
        lines.append(f"USD/INR: ₹{usdinr:.2f}")

    formatted = "\n".join(f"  {line}" for line in lines) if lines else "  (data unavailable)"

    return MacroContext(
        nifty_level=nifty_level,
        nifty_return_pct=nifty_return_pct,
        sector_name=sector_name,
        sector_return_pct=sector_return_pct,
        india_vix=india_vix,
        fii_net_cr=fii_net_cr,
        dii_net_cr=dii_net_cr,
        nifty_pcr=nifty_pcr,
        brent_price=brent_price,
        brent_ret_pct=brent_ret_pct,
        gold_price=gold_price,
        usdinr=usdinr,
        formatted=formatted,
    )
