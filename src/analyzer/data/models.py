"""Pydantic models for all data flowing between layers.

These are the typed contracts between modules. No dicts cross module boundaries.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, ConfigDict, model_serializer

# ── Raw data (adapter → data layer) ──────────────────────────────────────────


class StockData(BaseModel):
    """Raw OHLCV + ticker info for one stock. Produced by data/fetcher.py."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    symbol: str
    company_name: str
    ohlcv: pd.DataFrame
    current_price: float
    high_52w: float
    low_52w: float
    pct_from_low: float  # 0 = at 52w low, 100 = at 52w high
    info: dict[str, object]
    cashflow: pd.DataFrame | None
    balance_sheet: pd.DataFrame | None
    financials: pd.DataFrame | None

    @model_serializer(mode="plain")
    def _serialize(self) -> dict[str, object]:
        """Replace DataFrames with shape summaries so LangSmith can JSON-serialize the state."""

        def _df_summary(df: pd.DataFrame | None) -> str | None:
            return f"DataFrame[{df.shape[0]}×{df.shape[1]}]" if df is not None else None

        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "ohlcv": _df_summary(self.ohlcv),
            "current_price": self.current_price,
            "high_52w": self.high_52w,
            "low_52w": self.low_52w,
            "pct_from_low": self.pct_from_low,
            "info": self.info,
            "cashflow": _df_summary(self.cashflow),
            "balance_sheet": _df_summary(self.balance_sheet),
            "financials": _df_summary(self.financials),
        }


class DeliveryData(BaseModel):
    """NSE delivery % for one stock. Produced by data/fetcher.py."""

    delivery_pct: float | None
    delivery_date: str | None
    signal: str  # BUY | NEUTRAL | SELL (derived from pct + day return direction)
    label: str  # human-readable label for LLM prompt


class NewsItem(BaseModel):
    title: str
    summary: str
    publisher: str


class CorporateEvents(BaseModel):
    lines: list[str]
    context: str  # pre-formatted string for LLM prompt


# ── Indicator outputs (indicators/ layer) ─────────────────────────────────────


class TechnicalSignals(BaseModel):
    """12 technical votes + raw values for display. Produced by indicators/technical.py."""

    votes: dict[str, str]  # indicator_name → BUY | NEUTRAL | SELL

    rsi: float
    ma20: float
    ma50: float
    ma200: float
    macd_bullish: bool
    macd_reliable: bool
    volume_ratio: float
    stoch_k: float
    stoch_d: float
    bb_pct: float  # 0 = at lower band, 1 = at upper band
    williams_r: float
    cci: float
    pct_from_low: float

    delivery_signal: str  # pass-through from DeliveryData
    delivery_label: str

    # Display labels
    rsi_label: str
    trend_ma200: str
    macd_label: str
    vol_label: str
    w52_label: str


class FundamentalSignals(BaseModel):
    """15 fundamental votes + raw values. Produced by indicators/fundamental.py."""

    votes: dict[str, str]

    revenue_growth: float | None
    earnings_growth: float | None
    trailing_pe: float | None
    forward_pe: float | None
    peg_ratio: float | None
    price_to_book: float | None
    profit_margin: float | None
    ebitda_margins: float | None
    return_on_assets: float | None
    debt_to_equity: float | None
    current_ratio: float | None
    interest_coverage: float | None
    operating_cashflow: float | None
    free_cashflow: float | None
    net_income_ttm: float | None
    ocf_quality: float | None
    beta: float | None

    promoter_stake: float | None  # decimal (0.51 = 51%)
    inst_holding: float | None

    analyst_count: int
    analyst_mean: float | None
    analyst_label: str
    analyst_upside: float | None
    target_mean: float | None
    target_low: float | None
    target_high: float | None
    analyst_direction_vote: str
    analyst_direction_label: str


class IndiaSignals(BaseModel):
    """4 India-specific votes. Produced by indicators/india.py."""

    votes: dict[str, str]

    stock_pcr: float | None
    promoter_pledge_pct: float | None
    promoter_holding_pct: float | None
    institutional_holding_pct: float | None


class ScoringResult(BaseModel):
    """31-vote 3-category scoring. Produced by indicators/scoring.py."""

    tech_score: float  # -1 to +1
    fund_score: float
    india_score: float
    combined_score: float
    grade: str  # STRONG BUY | LEAN BUY | NEUTRAL | LEAN SELL | STRONG SELL

    tech_buy: int
    tech_neutral: int
    tech_sell: int
    fund_buy: int
    fund_neutral: int
    fund_sell: int
    india_buy: int
    india_neutral: int
    india_sell: int

    total_buy: int
    total_neutral: int
    total_sell: int
    total_votes: int

    tech_summary: str  # "LEAN BUY  8B · 3N · 1S"
    fund_summary: str
    india_summary: str
    combined_summary: str


# ── Context (data layer) ──────────────────────────────────────────────────────


class MacroContext(BaseModel):
    """4 PM post-close India market context. Produced by data/market_overview.py."""

    nifty_level: float | None
    nifty_return_pct: float | None
    sector_name: str
    sector_return_pct: float | None
    india_vix: float | None
    fii_net_cr: float | None  # FII net in crores (positive = buying)
    dii_net_cr: float | None
    nifty_pcr: float | None
    brent_price: float | None
    brent_ret_pct: float | None
    gold_price: float | None
    usdinr: float | None

    formatted: str  # pre-formatted block for LLM prompt


class GlobalCues(BaseModel):
    """8 AM pre-open global market data. Produced by data/global_cues.py."""

    sp_price: float | None
    sp_ret: float | None
    nq_price: float | None
    nq_ret: float | None
    dji_price: float | None
    dji_ret: float | None
    nk_price: float | None
    nk_ret: float | None
    hsi_price: float | None
    hsi_ret: float | None
    esf_price: float | None  # S&P futures (forward indicator)
    esf_ret: float | None
    brent_price: float | None
    brent_ret: float | None
    gold_price: float | None
    gold_ret: float | None
    usdinr: float | None
    global_read: list[str]  # list of rule-based plain-English observations


# ── LLM outputs ───────────────────────────────────────────────────────────────


class StockVerdict(BaseModel):
    """10-field structured verdict from the 4 PM LLM call."""

    signal: str  # BUY | SELL | HOLD
    confidence: float  # 0.0–1.0
    entry: int | None  # null for HOLD
    stop_loss: int | None  # null for HOLD
    target: int | None  # null for HOLD
    whats_happening: str
    why_it_matters: str
    watch_out_for: str
    trader_action: str
    investor_action: str

    input_tokens: int = 0
    output_tokens: int = 0

    # Phase 3A: whether reflection reviewed this verdict
    reflection_checked: bool = False
    reflection_overrode: bool = False


class MorningNote(BaseModel):
    """2–3 sentence morning update from the 8 AM LLM call."""

    symbol: str
    company_name: str
    previous_signal: str
    morning_text: str
    status: str  # INTACT | WEAKENED | STRENGTHENED
    input_tokens: int = 0
    output_tokens: int = 0


# ── Phase 3A additions ────────────────────────────────────────────────────────


class OutcomeRecord(BaseModel):
    """Tracks whether a past verdict played out correctly.

    Stored under outcomes/{verdict_date}/{symbol}.json.
    The /accuracy API endpoint reads these to compute running accuracy stats.
    """

    verdict_date: str  # ISO date when the verdict was produced
    symbol: str
    predicted_signal: str  # BUY | SELL | HOLD
    predicted_confidence: float
    predicted_entry: int | None
    predicted_target: int | None
    predicted_stop: int | None

    # Filled in the next trading day when we check actual price
    outcome_date: str | None = None
    actual_price: float | None = None
    direction_correct: bool | None = None  # None for HOLD (no direction to check)
    target_hit: bool | None = None
    stop_triggered: bool | None = None


class MorningNoteRecord(BaseModel):
    """Storage-ready morning note — saved to S3 and served by GET /morning.

    Wraps MorningNote with a date field so the API can index by date.
    """

    date: str  # ISO date e.g. "2025-04-27"
    symbol: str
    company_name: str
    previous_signal: str
    morning_text: str
    status: str  # INTACT | WEAKENED | STRENGTHENED

    @classmethod
    def from_note(cls, note: MorningNote, run_date: str) -> MorningNoteRecord:
        return cls(
            date=run_date,
            symbol=note.symbol,
            company_name=note.company_name,
            previous_signal=note.previous_signal,
            morning_text=note.morning_text,
            status=note.status,
        )
