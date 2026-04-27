"""8 AM pre-open global market data — US close, Asia, S&P futures, commodities."""

from __future__ import annotations

import structlog

from analyzer.adapters import yfinance as yf_adapter
from analyzer.data.models import GlobalCues

log = structlog.get_logger()


def _quote(sym: str) -> tuple[float | None, float | None]:
    h = yf_adapter.get_price_history(sym)
    if h.empty:
        return None, None
    price = float(h["Close"].iloc[-1])
    ret = (
        float((h["Close"].iloc[-1] - h["Close"].iloc[-2]) / h["Close"].iloc[-2] * 100)
        if len(h) >= 2
        else None
    )
    return price, ret


def _build_read(
    sp_ret: float | None,
    nk_ret: float | None,
    hsi_ret: float | None,
    esf_ret: float | None,
    brent_ret: float | None,
) -> list[str]:
    reads: list[str] = []
    if sp_ret is not None:
        if sp_ret < -1:
            reads.append(f"US fell {abs(sp_ret):.1f}% — gap-down open likely")
        elif sp_ret > 1:
            reads.append(f"US rose {sp_ret:.1f}% — positive carry-over expected")
    if nk_ret is not None and nk_ret < -1:
        reads.append("Nikkei weak — Asia risk-off")
    if hsi_ret is not None and hsi_ret < -1:
        reads.append("Hang Seng falling — China/HK risk-off")
    if brent_ret is not None and brent_ret > 2:
        reads.append(f"Oil up {brent_ret:.1f}% — inflation concern")
    if esf_ret is not None:
        if esf_ret > 0.5:
            reads.append("S&P futures positive — US likely strong tonight")
        elif esf_ret < -0.5:
            reads.append("S&P futures negative — potential headwind tonight")
    return reads


def fetch_global_cues() -> GlobalCues:
    log.info("fetch_global_cues")
    sp_price, sp_ret = _quote("^GSPC")
    nq_price, nq_ret = _quote("^IXIC")
    dji_price, dji_ret = _quote("^DJI")
    nk_price, nk_ret = _quote("^N225")
    hsi_price, hsi_ret = _quote("^HSI")
    esf_price, esf_ret = _quote("ES=F")
    brent_price, brent_ret = _quote("BZ=F")
    gold_price, gold_ret = _quote("GC=F")
    usdinr, _ = _quote("INR=X")

    global_read = _build_read(sp_ret, nk_ret, hsi_ret, esf_ret, brent_ret)

    return GlobalCues(
        sp_price=sp_price,
        sp_ret=sp_ret,
        nq_price=nq_price,
        nq_ret=nq_ret,
        dji_price=dji_price,
        dji_ret=dji_ret,
        nk_price=nk_price,
        nk_ret=nk_ret,
        hsi_price=hsi_price,
        hsi_ret=hsi_ret,
        esf_price=esf_price,
        esf_ret=esf_ret,
        brent_price=brent_price,
        brent_ret=brent_ret,
        gold_price=gold_price,
        gold_ret=gold_ret,
        usdinr=usdinr,
        global_read=global_read,
    )
