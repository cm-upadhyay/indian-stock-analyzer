"""Shared Pydantic state models for all LangGraph graph nodes.

Phase 3A additions to AnalysisState:
    memory_context     — loaded by inject_memory node (Task 3.1)
    outcome            — loaded by check_outcomes node (Task 3.2)
    nemo_blocked       — set by apply_nemo_rails node (Task 3.10)
    reflection_override — set by reflect node (Task 3.8)
    hitl_approved      — set by human_review node (Task 3.11)
    agentic_mode       — whether the LLM used tool-calling (Task 3.5)
"""

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
    OutcomeRecord,
    ScoringResult,
    StockData,
    StockVerdict,
    TechnicalSignals,
)
from analyzer.memory.context import MemoryContext


class AnalysisState(BaseModel):
    """State passed between nodes in the 4 PM analysis graph."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    symbol: str
    run_date: date = date.today()

    # ── Phase 2 fields (populated by nodes in order) ──────────────────────────
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

    # ── Phase 3A additions ────────────────────────────────────────────────────

    # Task 3.1 — Hierarchical memory: loaded before call_llm
    memory_context: MemoryContext = MemoryContext()

    # Task 3.2 — Outcome tracking: loaded at graph start
    outcome: OutcomeRecord | None = None

    # Task 3.5 — Agentic mode: True if LLM used tool calls this run
    agentic_mode_used: bool = False

    # Task 3.8 — Reflection: flags set by reflect node
    reflection_checked: bool = False
    reflection_overrode: bool = False

    # Task 3.10 — NeMo rails: True if output rail blocked the verdict
    nemo_blocked: bool = False

    # Task 3.11 — HITL:
    #   hitl_approved: True=approved, False=rejected, None=not triggered or pending
    #   hitl_pending:  True = interrupt() fired, awaiting admin decision (not yet published)
    hitl_approved: bool | None = None
    hitl_pending: bool = False

    # ── Error tracking ────────────────────────────────────────────────────────
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
