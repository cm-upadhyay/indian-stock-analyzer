"""Shared Pydantic state model for all LangGraph graph nodes."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from analyzer.data.models import (
    CorporateEvents,
    DeliveryData,
    FundamentalSignals,
    GlobalCues,
    IndiaSignals,
    MacroContext,
    MorningNote,
    NewsItem,
    ScoringResult,
    StockData,
    StockVerdict,
    TechnicalSignals,
)


class AnalysisState(BaseModel):
    """State passed between nodes in the 4 PM analysis graph."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    symbol: str
    run_date: date = date.today()

    # Populated by nodes in order
    stock: StockData | None = None
    delivery: DeliveryData | None = None
    tech: TechnicalSignals | None = None
    fund: FundamentalSignals | None = None
    india: IndiaSignals | None = None
    scoring: ScoringResult | None = None
    news: list[NewsItem] = []
    news_context: str = ""
    corporate: CorporateEvents | None = None
    macro: MacroContext | None = None
    verdict: StockVerdict | None = None

    # Error tracking
    error: str | None = None


class MorningState(BaseModel):
    """State passed between nodes in the 8 AM morning note graph."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    symbol: str
    company_name: str
    sector_name: str
    run_date: date = date.today()

    verdict: StockVerdict | None = None  # loaded from S3/local
    cues: GlobalCues | None = None
    morning_note: MorningNote | None = None

    error: str | None = None


class ScreenerState(BaseModel):
    """State for the top-level screener that drives the 4 PM pipeline."""

    symbols: list[str] = []
    run_date: date = date.today()
    analyses: list[AnalysisState] = []
    completed: int = 0
    failed: int = 0
