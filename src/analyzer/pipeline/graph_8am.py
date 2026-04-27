"""8 AM morning note LangGraph graph.

Node sequence:
    load_verdict → fetch_global_cues → call_morning_llm → publish_morning

Reads yesterday's verdict from storage (S3/local) and produces a morning note.
"""

from __future__ import annotations

from datetime import timedelta

import structlog
from langgraph.graph import END, START, StateGraph

from analyzer.data.global_cues import fetch_global_cues
from analyzer.data.market_overview import _SECTOR_MAP
from analyzer.llm.morning import call_morning_note
from analyzer.pipeline.state import MorningState
from analyzer.utils.storage import AnalysisStore

log = structlog.get_logger()
_store = AnalysisStore()


# ── Nodes ─────────────────────────────────────────────────────────────────────


def node_load_verdict(state: MorningState) -> MorningState:
    log.info("load_verdict", symbol=state.symbol)
    # Walk back up to 3 days to skip weekends
    for days_back in range(1, 4):
        check_date = state.run_date - timedelta(days=days_back)
        verdict = _store.load(check_date, state.symbol)
        if verdict:
            log.info("verdict_loaded", symbol=state.symbol, date=str(check_date))
            return state.model_copy(update={"verdict": verdict})
    log.warning("no_verdict_found", symbol=state.symbol)
    return state.model_copy(update={"error": "no verdict found for this symbol"})


def node_fetch_global_cues(state: MorningState) -> MorningState:
    log.info("fetch_global_cues")
    try:
        cues = fetch_global_cues()
        return state.model_copy(update={"cues": cues})
    except Exception as e:
        log.warning("fetch_global_cues_failed", error=str(e))
        return state


def node_call_morning_llm(state: MorningState) -> MorningState:
    if state.verdict is None or state.cues is None:
        return state.model_copy(update={"error": "call_morning_llm: missing verdict or cues"})
    log.info("call_morning_llm", symbol=state.symbol)
    note = call_morning_note(
        symbol=state.symbol,
        company_name=state.company_name,
        sector_name=state.sector_name,
        verdict=state.verdict,
        cues=state.cues,
    )
    log.info("morning_llm_done", symbol=state.symbol, status=note.status)
    return state.model_copy(update={"morning_note": note})


def node_publish_morning(state: MorningState) -> MorningState:
    if state.morning_note is None:
        return state
    log.info("publish_morning", symbol=state.symbol, status=state.morning_note.status)
    # Notification (Telegram/email) is handled by the caller after the graph returns
    return state


# ── Graph ─────────────────────────────────────────────────────────────────────


def build_8am_graph() -> StateGraph[MorningState]:
    g = StateGraph(MorningState)

    g.add_node("load_verdict", node_load_verdict)
    g.add_node("fetch_global_cues", node_fetch_global_cues)
    g.add_node("call_morning_llm", node_call_morning_llm)
    g.add_node("publish_morning", node_publish_morning)

    g.add_edge(START, "load_verdict")
    g.add_edge("load_verdict", "fetch_global_cues")
    g.add_edge("fetch_global_cues", "call_morning_llm")
    g.add_edge("call_morning_llm", "publish_morning")
    g.add_edge("publish_morning", END)

    return g


def run_8am(symbol: str, company_name: str) -> MorningState:
    """Run the 8 AM morning note pipeline for a single stock."""
    _, sector_name = _SECTOR_MAP.get(symbol, ("^NSEI", "Nifty 50"))
    graph = build_8am_graph().compile()
    initial = MorningState(symbol=symbol, company_name=company_name, sector_name=sector_name)
    result = graph.invoke(initial)
    return MorningState(**result)
