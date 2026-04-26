"""15 fundamental votes — pure computation, zero external calls.

Input: StockData (info dict + financial statements).
Output: FundamentalSignals with votes dict and raw values for display.
"""

from __future__ import annotations

import pandas as pd

from analyzer.data.models import FundamentalSignals, StockData


def _stmt_val(df: pd.DataFrame | None, keys: list[str]) -> float | None:
    """Return first non-null value matching any key in a statement DataFrame."""
    if df is None or df.empty:
        return None
    for k in keys:
        if k in df.index:
            v = df.loc[k].iloc[0]
            if pd.notna(v):
                return float(v)
    return None


def _fvote(
    val: float | None,
    buy_thresh: float,
    sell_thresh: float,
    higher_is_better: bool = True,
) -> str:
    if val is None:
        return "NEUTRAL"
    if higher_is_better:
        return "BUY" if val >= buy_thresh else "SELL" if val <= sell_thresh else "NEUTRAL"
    else:
        return "BUY" if val <= buy_thresh else "SELL" if val >= sell_thresh else "NEUTRAL"


def _analyst_direction(recommendations: pd.DataFrame | None) -> tuple[str, str]:
    if recommendations is None or recommendations.empty:
        return "NEUTRAL", "stable"

    def bull_frac(row: pd.Series[object]) -> float:
        sb = int(row.get("strongBuy", 0) or 0)
        b = int(row.get("buy", 0) or 0)
        s = int(row.get("sell", 0) or 0)
        ss = int(row.get("strongSell", 0) or 0)
        h = int(row.get("hold", 0) or 0)
        total = sb + b + h + s + ss
        return (sb + b) / total if total > 0 else 0.5

    current = bull_frac(recommendations.iloc[0])
    older = bull_frac(recommendations.iloc[min(2, len(recommendations) - 1)])

    if current > older + 0.08:
        return "BUY", "improving — more upgrades recently"
    elif current < older - 0.08:
        return "SELL", "deteriorating — more downgrades recently"
    return "NEUTRAL", "stable"


def compute_fundamental(stock: StockData) -> FundamentalSignals:
    info = stock.info
    cf = stock.cashflow
    bs = stock.balance_sheet
    fin = stock.financials

    # ── From ticker.info ──────────────────────────────────────────────────────
    revenue_growth = info.get("revenueGrowth")
    earnings_growth = info.get("earningsGrowth")
    trailing_pe = info.get("trailingPE")
    forward_pe = info.get("forwardPE")
    peg_ratio = info.get("pegRatio")
    price_to_book = info.get("priceToBook")
    profit_margin = info.get("profitMargins")
    ebitda_margins = info.get("ebitdaMargins")
    return_on_assets = info.get("returnOnAssets")
    debt_to_equity = info.get("debtToEquity")
    current_ratio = info.get("currentRatio")
    operating_cashflow: float | None = info.get("operatingCashflow")
    free_cashflow: float | None = info.get("freeCashflow")
    net_income_ttm: float | None = info.get("netIncomeToCommon")
    promoter_stake = info.get("heldPercentInsiders")
    inst_holding = info.get("heldPercentInstitutions")
    beta = info.get("beta")
    analyst_count: int = info.get("numberOfAnalystOpinions") or 0
    analyst_mean = info.get("recommendationMean")
    analyst_label: str = info.get("averageAnalystRating") or ""
    target_low = info.get("targetLowPrice")
    target_mean = info.get("targetMeanPrice")
    target_high = info.get("targetHighPrice")
    analyst_upside = (
        (target_mean / stock.current_price - 1) * 100
        if target_mean and stock.current_price
        else None
    )

    # ── Fallback: financial statements for fields info misses on NSE stocks ──
    if operating_cashflow is None:
        operating_cashflow = _stmt_val(
            cf,
            [
                "Operating Cash Flow",
                "Cash From Operating Activities",
                "Total Cash From Operating Activities",
                "Net Cash From Operating Activities",
            ],
        )
    if free_cashflow is None:
        free_cashflow = _stmt_val(cf, ["Free Cash Flow", "FreeCashFlow"])
    if current_ratio is None and bs is not None:
        ca = _stmt_val(bs, ["Current Assets", "Total Current Assets"])
        cl = _stmt_val(bs, ["Current Liabilities", "Total Current Liabilities"])
        if ca and cl and cl > 0:
            current_ratio = ca / cl
    if return_on_assets is None and bs is not None:
        total_assets = _stmt_val(bs, ["Total Assets"])
        net_inc = _stmt_val(
            fin,
            [
                "Net Income",
                "Net Income Common Stockholders",
                "Net Income From Continuing Operations",
            ],
        )
        if total_assets and net_inc and total_assets > 0:
            return_on_assets = net_inc / total_assets

    # ── Derived metrics ───────────────────────────────────────────────────────
    ocf_quality: float | None = None
    if operating_cashflow and net_income_ttm and net_income_ttm > 0:
        ocf_quality = operating_cashflow / net_income_ttm

    interest_coverage: float | None = None
    if fin is not None and not fin.empty:
        ebit = _stmt_val(fin, ["EBIT", "Operating Income", "OperatingIncome"])
        intexp = _stmt_val(fin, ["Interest Expense", "InterestExpense"])
        if ebit is not None and intexp is not None and intexp != 0:
            interest_coverage = abs(ebit / intexp)

    # ── Analyst direction ─────────────────────────────────────────────────────
    # Import here to avoid circular — yfinance adapter call is NOT here; caller passes recs
    # Recommendations come from stock.info flow; we'd need a separate adapter call.
    # For now: derive from info if available, otherwise NEUTRAL.
    analyst_direction_vote = "NEUTRAL"
    analyst_direction_label = "stable"

    # ── Votes ─────────────────────────────────────────────────────────────────
    votes: dict[str, str] = {
        # Growth
        "Revenue_Growth": _fvote(revenue_growth, 0.15, 0.05),
        "Earnings_Growth": _fvote(earnings_growth, 0.10, 0.00),
        # Profitability
        "Net_Margin": _fvote(profit_margin, 0.15, 0.05),
        "EBITDA_Margin": _fvote(ebitda_margins, 0.20, 0.10),
        "Return_on_Assets": _fvote(return_on_assets, 0.08, 0.03),
        # Cash flow
        "OCF_Quality": _fvote(ocf_quality, 0.9, 0.5),
        "Free_Cash_Flow": (
            "BUY"
            if free_cashflow and free_cashflow > 0
            else "SELL"
            if free_cashflow and free_cashflow < 0
            else "NEUTRAL"
        ),
        # Valuation
        "Trailing_PE": _fvote(trailing_pe, 18.0, 30.0, higher_is_better=False),
        "PEG_Ratio": _fvote(peg_ratio, 1.0, 2.0, higher_is_better=False),
        # Financial health
        "Debt_Equity": _fvote(debt_to_equity, 50.0, 100.0, higher_is_better=False),
        "Current_Ratio": _fvote(current_ratio, 2.0, 1.0),
        "Interest_Coverage": _fvote(interest_coverage, 3.0, 1.5),
        # Analyst
        "Analyst_Rating": _fvote(analyst_mean, 2.0, 3.0, higher_is_better=False),
        "Analyst_Upside": _fvote(analyst_upside, 20.0, 0.0),
        "Analyst_Direction": analyst_direction_vote,
    }

    return FundamentalSignals(
        votes=votes,
        revenue_growth=revenue_growth,
        earnings_growth=earnings_growth,
        trailing_pe=trailing_pe,
        forward_pe=forward_pe,
        peg_ratio=peg_ratio,
        price_to_book=price_to_book,
        profit_margin=profit_margin,
        ebitda_margins=ebitda_margins,
        return_on_assets=return_on_assets,
        debt_to_equity=debt_to_equity,
        current_ratio=current_ratio,
        interest_coverage=interest_coverage,
        operating_cashflow=operating_cashflow,
        free_cashflow=free_cashflow,
        net_income_ttm=net_income_ttm,
        ocf_quality=ocf_quality,
        beta=beta,
        promoter_stake=promoter_stake,
        inst_holding=inst_holding,
        analyst_count=analyst_count,
        analyst_mean=analyst_mean,
        analyst_label=analyst_label,
        analyst_upside=analyst_upside,
        target_mean=target_mean,
        target_low=target_low,
        target_high=target_high,
        analyst_direction_vote=analyst_direction_vote,
        analyst_direction_label=analyst_direction_label,
    )
