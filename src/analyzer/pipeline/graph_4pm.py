"""4 PM analysis LangGraph graph.

Node sequence:
    fetch_data → fetch_delivery → compute_technical → fetch_fundamentals
    → fetch_india → score_all → fetch_news → fetch_corporate → fetch_macro
    → call_llm → publish

Write ADR-001 (LangGraph over CrewAI) before modifying this file.
"""

from __future__ import annotations

import structlog
from langgraph.graph import END, START, StateGraph

from analyzer.adapters import nse as nse_adapter
from analyzer.data import corporate as corp_module
from analyzer.data import market_overview as macro_module
from analyzer.data import news as news_module
from analyzer.data.fetcher import fetch_delivery_data, fetch_stock_data
from analyzer.data.models import DeliveryData
from analyzer.indicators import india as india_module
from analyzer.indicators import scoring as scoring_module
from analyzer.indicators import technical as tech_module
from analyzer.indicators.fundamental import compute_fundamental
from analyzer.llm.analyst import call_analyst
from analyzer.pipeline.state import AnalysisState
from analyzer.utils.storage import AnalysisStore

log = structlog.get_logger()
_store = AnalysisStore()


# ── Nodes ─────────────────────────────────────────────────────────────────────


def node_fetch_data(state: AnalysisState) -> AnalysisState:
    log.info("fetch_data", symbol=state.symbol)
    try:
        stock = fetch_stock_data(state.symbol)
        return state.model_copy(update={"stock": stock})
    except Exception as e:
        return state.model_copy(update={"error": f"fetch_data: {e}"})


def node_fetch_delivery(state: AnalysisState) -> AnalysisState:
    if state.stock is None:
        return state
    log.info("fetch_delivery", symbol=state.symbol)
    close = state.stock.ohlcv["Close"]
    prev_price = float(close.iloc[-2]) if len(close) >= 2 else state.stock.current_price
    delivery = fetch_delivery_data(state.symbol, state.stock.current_price, prev_price)
    return state.model_copy(update={"delivery": delivery})


def node_compute_technical(state: AnalysisState) -> AnalysisState:
    if state.stock is None:
        return state
    log.info("compute_technical", symbol=state.symbol)
    delivery = state.delivery or DeliveryData(
        delivery_pct=None, delivery_date=None, signal="NEUTRAL", label="unavailable"
    )
    tech = tech_module.compute_technical(
        ohlcv=state.stock.ohlcv,
        current_price=state.stock.current_price,
        high_52w=state.stock.high_52w,
        low_52w=state.stock.low_52w,
        pct_from_low=state.stock.pct_from_low,
        delivery_signal=delivery.signal,
        delivery_label=delivery.label,
    )
    return state.model_copy(update={"tech": tech})


def node_fetch_fundamentals(state: AnalysisState) -> AnalysisState:
    if state.stock is None:
        return state
    log.info("fetch_fundamentals", symbol=state.symbol)
    fund = compute_fundamental(state.stock)
    return state.model_copy(update={"fund": fund})


def node_fetch_india(state: AnalysisState) -> AnalysisState:
    if state.stock is None or state.fund is None:
        return state
    log.info("fetch_india", symbol=state.symbol)
    nse_sym = state.symbol.replace(".NS", "")
    oc_data = nse_adapter.get_option_chain_equity(nse_sym)
    pledge_data = nse_adapter.get_pledge_data(nse_sym)
    india = india_module.compute_india_signals(
        option_chain_data=oc_data,
        pledge_data=pledge_data,
        promoter_stake=state.fund.promoter_stake,
        inst_holding=state.fund.inst_holding,
    )
    return state.model_copy(update={"india": india})


def node_score_all(state: AnalysisState) -> AnalysisState:
    if state.tech is None or state.fund is None or state.india is None:
        return state
    log.info("score_all", symbol=state.symbol)
    scoring = scoring_module.compute_scoring(state.tech, state.fund, state.india)
    return state.model_copy(update={"scoring": scoring})


def node_fetch_news(state: AnalysisState) -> AnalysisState:
    log.info("fetch_news", symbol=state.symbol)
    news = news_module.fetch_news(state.symbol)
    news_context = news_module.format_news_context(news)
    return state.model_copy(update={"news": news, "news_context": news_context})


def node_fetch_corporate(state: AnalysisState) -> AnalysisState:
    log.info("fetch_corporate", symbol=state.symbol)
    corporate = corp_module.fetch_corporate_events(state.symbol)
    return state.model_copy(update={"corporate": corporate})


def node_fetch_macro(state: AnalysisState) -> AnalysisState:
    log.info("fetch_macro", symbol=state.symbol)
    try:
        macro = macro_module.fetch_market_overview(state.symbol)
        return state.model_copy(update={"macro": macro})
    except Exception as e:
        log.warning("fetch_macro_failed", error=str(e))
        return state


def node_call_llm(state: AnalysisState) -> AnalysisState:
    stock = state.stock
    tech = state.tech
    fund = state.fund
    india = state.india
    scoring = state.scoring
    corporate = state.corporate
    if any(x is None for x in [stock, tech, fund, india, scoring, corporate]):
        return state.model_copy(update={"error": "call_llm: missing required state"})

    log.info("call_llm", symbol=state.symbol)
    verdict = call_analyst(
        stock=stock,
        tech=tech,
        fund=fund,
        india=india,
        scoring=scoring,
        news=state.news,
        news_context=state.news_context,
        corporate=corporate,
        macro=state.macro,
    )
    log.info("llm_done", symbol=state.symbol, signal=verdict.signal, confidence=verdict.confidence)
    return state.model_copy(update={"verdict": verdict})


def node_publish(state: AnalysisState) -> AnalysisState:
    if state.verdict is None:
        return state
    log.info("publish", symbol=state.symbol, signal=state.verdict.signal)
    _store.save(state.run_date, state.symbol, state.verdict)
    return state


def _should_continue(state: AnalysisState) -> str:
    return "error" if state.error else "continue"


# ── Graph ─────────────────────────────────────────────────────────────────────


def build_4pm_graph() -> StateGraph[AnalysisState]:
    g = StateGraph(AnalysisState)

    g.add_node("fetch_data", node_fetch_data)
    g.add_node("fetch_delivery", node_fetch_delivery)
    g.add_node("compute_technical", node_compute_technical)
    g.add_node("fetch_fundamentals", node_fetch_fundamentals)
    g.add_node("fetch_india", node_fetch_india)
    g.add_node("score_all", node_score_all)
    g.add_node("fetch_news", node_fetch_news)
    g.add_node("fetch_corporate", node_fetch_corporate)
    g.add_node("fetch_macro", node_fetch_macro)
    g.add_node("call_llm", node_call_llm)
    g.add_node("publish", node_publish)

    g.add_edge(START, "fetch_data")
    g.add_edge("fetch_data", "fetch_delivery")
    g.add_edge("fetch_delivery", "compute_technical")
    g.add_edge("compute_technical", "fetch_fundamentals")
    g.add_edge("fetch_fundamentals", "fetch_india")
    g.add_edge("fetch_india", "score_all")
    g.add_edge("score_all", "fetch_news")
    g.add_edge("fetch_news", "fetch_corporate")
    g.add_edge("fetch_corporate", "fetch_macro")
    g.add_edge("fetch_macro", "call_llm")
    g.add_edge("call_llm", "publish")
    g.add_edge("publish", END)

    return g


def run_4pm(symbol: str) -> AnalysisState:
    """Run the full 4 PM pipeline for a single stock."""
    graph = build_4pm_graph().compile()
    initial = AnalysisState(symbol=symbol)
    result = graph.invoke(initial)
    return AnalysisState(**result)
