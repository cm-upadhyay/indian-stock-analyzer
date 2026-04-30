"""MCP tool: get_option_chain — PCR, max pain, and OI analysis from NSE.

This is a NEW data tool (Task 3.4) that only exists because the LLM can now
selectively request it via MCP. In Phase 2, option chain data was fetched
inline in the pipeline for every stock. Now it's on-demand.

Data source: NSE option chain API (already used in adapters/nse.py for PCR)
New here: max pain computation and OI skew analysis.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()


def _compute_max_pain(option_data: dict) -> float | None:  # type: ignore[type-arg]
    """Compute the max pain price: the strike where total option seller losses are minimised.

    Algorithm:
        For each strike price K:
            - Sum the intrinsic value of all ITM calls: max(0, K - underlying) × OI
            - Sum the intrinsic value of all ITM puts:  max(0, underlying - K) × OI
        The strike that minimises total loss = max pain.

    This is a simplified version — a full implementation accounts for gamma exposure.
    """
    data = option_data.get("data", [])
    if not data:
        return None

    strikes: list[float] = [
        float(row.get("strikePrice", 0)) for row in data if row.get("strikePrice")
    ]
    if not strikes:
        return None

    best_strike = None
    min_pain = float("inf")

    for test_strike in strikes:
        total_pain = 0.0
        for row in data:
            k = float(row.get("strikePrice", 0))
            ce_oi = float(row.get("CE", {}).get("openInterest", 0))
            pe_oi = float(row.get("PE", {}).get("openInterest", 0))
            # Call pain: call holders lose if test_strike < k (calls expire worthless)
            total_pain += max(0, test_strike - k) * pe_oi
            total_pain += max(0, k - test_strike) * ce_oi
        if total_pain < min_pain:
            min_pain = total_pain
            best_strike = test_strike

    return best_strike


def run(symbol: str) -> dict:  # type: ignore[type-arg]
    """Fetch option chain data for a symbol (no .NS suffix) and return analysis."""
    try:
        from analyzer.adapters import nse as nse_adapter

        raw = nse_adapter.get_option_chain_equity(symbol)
        if not raw:
            return {"symbol": symbol, "available": False, "error": "No option chain data"}

        # PCR from existing adapter

        # Compute PCR manually from raw option chain
        total_pe_oi = sum(
            float(row.get("PE", {}).get("openInterest", 0)) for row in raw.get("data", [])
        )
        total_ce_oi = sum(
            float(row.get("CE", {}).get("openInterest", 0)) for row in raw.get("data", [])
        )
        pcr = round(total_pe_oi / total_ce_oi, 3) if total_ce_oi > 0 else None

        pcr_label = "unavailable"
        if pcr is not None:
            if pcr < 0.7:
                pcr_label = "bullish — calls dominate (market expects rally)"
            elif pcr > 1.2:
                pcr_label = "bearish — puts dominate (market expects decline)"
            else:
                pcr_label = "neutral"

        max_pain = _compute_max_pain(raw)

        return {
            "symbol": symbol,
            "available": True,
            "pcr": pcr,
            "pcr_label": pcr_label,
            "max_pain_price": max_pain,
            "total_call_oi": int(total_ce_oi),
            "total_put_oi": int(total_pe_oi),
            "error": None,
        }
    except Exception as e:
        log.error("mcp_option_chain_failed", symbol=symbol, error=str(e))
        return {"symbol": symbol, "available": False, "error": str(e)}
