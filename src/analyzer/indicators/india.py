"""4 India-specific votes — pure computation, zero external calls.

Input: raw NSE API data (option chain, pledge, holdings from adapters).
Output: IndiaSignals with votes dict.
"""

from __future__ import annotations

from analyzer.data.models import IndiaSignals


def _pcr_from_option_chain(oc_data: list[dict]) -> float | None:  # type: ignore[type-arg]
    if not oc_data:
        return None
    ce_oi = sum(r.get("CE", {}).get("openInterest", 0) for r in oc_data if "CE" in r)
    pe_oi = sum(r.get("PE", {}).get("openInterest", 0) for r in oc_data if "PE" in r)
    return pe_oi / ce_oi if ce_oi > 0 else None


def _pledge_pct_from_data(pledge_rows: list[dict]) -> float | None:  # type: ignore[type-arg]
    if not pledge_rows:
        return None
    for key in [
        "pledgedSharesPerc",
        "pledgePerc",
        "pledgePercent",
        "promoterAndPromoterGroupPercentagePledge",
        "promoterPledgePerc",
    ]:
        if key in pledge_rows[0]:
            try:
                return float(pledge_rows[0][key])
            except (ValueError, TypeError):
                pass
    return None


def compute_india_signals(
    option_chain_data: list[dict],  # type: ignore[type-arg]
    pledge_data: list[dict],  # type: ignore[type-arg]
    promoter_stake: float | None,  # decimal from ticker.info
    inst_holding: float | None,  # decimal from ticker.info
) -> IndiaSignals:
    stock_pcr = _pcr_from_option_chain(option_chain_data)
    promoter_pledge_pct = _pledge_pct_from_data(pledge_data)
    promoter_holding_pct = promoter_stake * 100 if promoter_stake is not None else None
    institutional_holding_pct = inst_holding * 100 if inst_holding is not None else None

    votes: dict[str, str] = {}

    # Promoter holding: 35–70% is ideal (aligned with company + enough float)
    ph = promoter_holding_pct
    if ph is None:
        votes["Promoter_Holding"] = "NEUTRAL"
    elif 35 <= ph <= 70:
        votes["Promoter_Holding"] = "BUY"
    elif ph < 20:
        votes["Promoter_Holding"] = "SELL"
    else:
        votes["Promoter_Holding"] = "NEUTRAL"

    # Promoter pledge: <5% = no stress, >25% = forced-selling risk
    pp = promoter_pledge_pct
    if pp is None:
        votes["Promoter_Pledge"] = "NEUTRAL"
    elif pp < 5:
        votes["Promoter_Pledge"] = "BUY"
    elif pp > 25:
        votes["Promoter_Pledge"] = "SELL"
    else:
        votes["Promoter_Pledge"] = "NEUTRAL"

    # Stock PCR: <0.7 = bullish (calls > puts), >1.2 = bearish (heavy hedging)
    pcr = stock_pcr
    if pcr is None:
        votes["Stock_PCR"] = "NEUTRAL"
    elif pcr < 0.7:
        votes["Stock_PCR"] = "BUY"
    elif pcr > 1.2:
        votes["Stock_PCR"] = "SELL"
    else:
        votes["Stock_PCR"] = "NEUTRAL"

    # Institutional holdings: >30% = smart money present, <10% = funds avoiding
    ih = institutional_holding_pct
    if ih is None:
        votes["Institutional_Holdings"] = "NEUTRAL"
    elif ih > 30:
        votes["Institutional_Holdings"] = "BUY"
    elif ih < 10:
        votes["Institutional_Holdings"] = "SELL"
    else:
        votes["Institutional_Holdings"] = "NEUTRAL"

    return IndiaSignals(
        votes=votes,
        stock_pcr=stock_pcr,
        promoter_pledge_pct=promoter_pledge_pct,
        promoter_holding_pct=promoter_holding_pct,
        institutional_holding_pct=institutional_holding_pct,
    )
