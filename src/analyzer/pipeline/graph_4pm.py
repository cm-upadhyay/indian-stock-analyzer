"""4 PM analysis LangGraph graph — Phase 3A.

Node sequence (Phase 3A):
    check_outcomes      [NEW 3.2] load past verdict + evaluate outcome
    inject_memory       [NEW 3.1] load Mem0 memory context
    fetch_data          [Phase 2] OHLCV + ticker info
    fetch_delivery      [Phase 2] NSE delivery %
    validate_frames     [NEW 3.7] Pandera OHLCV validation
    compute_technical   [Phase 2] 12 technical votes
    fetch_fundamentals  [Phase 2] 15 fundamental votes
    fetch_india         [Phase 2] 4 India-specific votes
    score_all           [Phase 2] 31-vote combined score
    fetch_news          [Phase 2] yfinance news
    sanitize_inputs     [NEW 3.12] LLM Guard + Presidio on news
    fetch_corporate     [Phase 2] corporate events
    fetch_macro         [Phase 2] market overview
    call_llm            [Phase 2+] agentic tool-calling (Task 3.5) + guardrails (Task 3.9)
    apply_nemo_rails    [NEW 3.10] NeMo policy output rail
    reflect             [NEW 3.8]  smart-triggered reviewer
    human_review        [NEW 3.11] HITL approval gate
    publish             [Phase 2+] save verdict + save memory (Task 3.1)

Write ADR-001 (LangGraph) and ADR-006 (Mem0) before modifying this file.
"""

from __future__ import annotations

import os

import structlog
from langgraph.graph import END, START, StateGraph

from analyzer.adapters import nse as nse_adapter
from analyzer.data import corporate as corp_module
from analyzer.data import market_overview as macro_module
from analyzer.data import news as news_module
from analyzer.data.fetcher import fetch_delivery_data, fetch_stock_data
from analyzer.data.models import DeliveryData, StockVerdict
from analyzer.guardrails.nemo_rails.rails import apply_output_rail
from analyzer.guardrails.schema_guards import validate_verdict
from analyzer.hitl.approver import (
    send_approval_request,
    should_trigger_hitl,
)
from analyzer.indicators import india as india_module
from analyzer.indicators import scoring as scoring_module
from analyzer.indicators import technical as tech_module
from analyzer.indicators.fundamental import compute_fundamental
from analyzer.llm.analyst import call_analyst
from analyzer.llm.reviewer import call_reviewer, should_reflect
from analyzer.memory.store import MemoryStore
from analyzer.outcomes.tracker import check_and_store_outcome
from analyzer.pipeline.state import AnalysisState
from analyzer.schemas.dataframes import validate_ohlcv
from analyzer.security.input_guard import sanitize_news_items
from analyzer.utils.budget import get_budget
from analyzer.utils.storage import AnalysisStore

log = structlog.get_logger()
_store = AnalysisStore()
_memory = MemoryStore()


# ── Phase 3A nodes ────────────────────────────────────────────────────────────


def node_check_outcomes(state: AnalysisState) -> AnalysisState:
    """Task 3.2 — Check whether the most recent past verdict for this stock played out."""
    log.info("check_outcomes", symbol=state.symbol)
    # We need the current price to evaluate the outcome.
    # Fetch a lightweight quote here (just price, no full OHLCV).
    try:
        import yfinance as yf

        ticker = yf.Ticker(state.symbol)
        current_price = ticker.fast_info.last_price or 0.0
        if current_price > 0:
            outcome = check_and_store_outcome(state.symbol, current_price)
            if outcome:
                _memory.add_outcome_result(state.symbol, outcome)
                return state.model_copy(update={"outcome": outcome})
    except Exception as e:
        log.warning("check_outcomes_failed", symbol=state.symbol, error=str(e))
    return state


def node_inject_memory(state: AnalysisState) -> AnalysisState:
    """Task 3.1 — Load hierarchical memory (episodic + semantic + procedural) for this stock."""
    log.info("inject_memory", symbol=state.symbol)
    try:
        context = _memory.get_context(state.symbol)
        return state.model_copy(update={"memory_context": context})
    except Exception as e:
        log.warning("inject_memory_failed", symbol=state.symbol, error=str(e))
        return state


def node_validate_frames(state: AnalysisState) -> AnalysisState:
    """Task 3.7 — Pandera validation of the OHLCV DataFrame."""
    if state.stock is None:
        return state
    log.info("validate_frames", symbol=state.symbol)
    try:
        validated_df = validate_ohlcv(state.stock.ohlcv, state.symbol)
        updated_stock = state.stock.model_copy(update={"ohlcv": validated_df})
        return state.model_copy(update={"stock": updated_stock})
    except ValueError as e:
        log.error("ohlcv_invalid", symbol=state.symbol, error=str(e))
        return state.model_copy(update={"error": f"validate_frames: {e}"})


def node_sanitize_inputs(state: AnalysisState) -> AnalysisState:
    """Task 3.12 — LLM Guard on news + Presidio PII redaction."""
    log.info("sanitize_inputs", symbol=state.symbol)
    try:
        raw_items = [
            {"title": n.title, "summary": n.summary, "publisher": n.publisher} for n in state.news
        ]
        cleaned = sanitize_news_items(raw_items, state.symbol)

        from analyzer.data.models import NewsItem

        clean_news = [
            NewsItem(title=d["title"], summary=d["summary"], publisher=d["publisher"])
            for d in cleaned
        ]
        clean_context = news_module.format_news_context(clean_news)
        return state.model_copy(update={"news": clean_news, "news_context": clean_context})
    except Exception as e:
        log.warning("sanitize_inputs_failed", symbol=state.symbol, error=str(e))
        return state


def node_apply_nemo_rails(state: AnalysisState) -> AnalysisState:
    """Task 3.10 — NeMo Guardrails output policy rail."""
    if state.verdict is None:
        return state
    log.info("apply_nemo_rails", symbol=state.symbol)
    verdict_summary = (
        f"Signal: {state.verdict.signal}, "
        f"Entry: {state.verdict.entry}, "
        f"Analysis: {state.verdict.whats_happening}"
    )
    _, blocked = apply_output_rail(verdict_summary, state.symbol)
    if blocked:
        log.warning("nemo_output_blocked", symbol=state.symbol)
        return state.model_copy(
            update={
                "nemo_blocked": True,
                "error": "nemo_rails: output policy violation — verdict not published",
            }
        )
    return state


def node_reflect(state: AnalysisState) -> AnalysisState:
    """Task 3.8 — Smart-triggered reflection: reviewer model checks uncertain verdicts."""
    if state.verdict is None or state.error:
        return state

    if not should_reflect(state.verdict, state.tech, state.news_context):
        return state

    log.info("reflect", symbol=state.symbol, signal=state.verdict.signal)
    current_price = state.stock.current_price if state.stock else 0.0

    # Build a summary of the analysis data for the reviewer
    summary_lines = [f"Stock: {state.symbol}"]
    if state.tech:
        summary_lines.append(f"Technical: {state.scoring.tech_summary if state.scoring else 'N/A'}")
        summary_lines.append(f"RSI {state.tech.rsi:.1f} | {state.tech.trend_ma200}")
    if state.news_context:
        summary_lines.append(f"News: {state.news_context[:300]}")
    user_msg_summary = "\n".join(summary_lines)

    final_verdict, was_overridden = call_reviewer(
        symbol=state.symbol,
        verdict=state.verdict,
        user_message_summary=user_msg_summary,
        current_price=current_price,
    )
    updated_verdict = final_verdict.model_copy(
        update={
            "reflection_checked": True,
            "reflection_overrode": was_overridden,
        }
    )
    return state.model_copy(
        update={
            "verdict": updated_verdict,
            "reflection_checked": True,
            "reflection_overrode": was_overridden,
        }
    )


def node_human_review(state: AnalysisState) -> AnalysisState:
    """Task 3.11 — HITL approval gate for high-stakes verdicts."""
    if state.verdict is None or state.error:
        return state

    if not should_trigger_hitl(
        verdict=state.verdict,
        reflection_overrode=state.reflection_overrode,
        nemo_soft_flag=state.nemo_blocked,
    ):
        return state.model_copy(update={"hitl_approved": None})  # not triggered

    thread_id = f"{state.symbol}_{state.run_date}"
    log.info("human_review_triggered", symbol=state.symbol, thread_id=thread_id)

    sent = send_approval_request(thread_id, state.symbol, state.verdict)
    if not sent:
        log.warning("hitl_send_failed_auto_approve", symbol=state.symbol)
        return state.model_copy(update={"hitl_approved": True})  # fail-open on send error

    # Phase 3A: fire-and-forget — send the Telegram request and drop the verdict.
    # Blocking here (wait_for_decision) would stall all remaining stocks in the batch
    # and risk Lambda timeout. Phase 4 replaces this with the LangGraph interrupt/resume
    # pattern backed by DynamoDB so the verdict can be resumed after admin approval.
    log.info("hitl_pending_dropped", symbol=state.symbol, thread_id=thread_id)
    return state.model_copy(
        update={
            "hitl_approved": False,
            "error": "hitl: verdict held for admin review — not published (Phase 4 will resume)",
        }
    )


# ── Phase 2 nodes (unchanged) ─────────────────────────────────────────────────


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
    """Task 3.5 agentic mode + Task 3.9 schema guardrails."""
    stock = state.stock
    tech = state.tech
    fund = state.fund
    india = state.india
    scoring = state.scoring
    corporate = state.corporate
    if any(x is None for x in [stock, tech, fund, india, scoring, corporate]):
        return state.model_copy(update={"error": "call_llm: missing required state"})

    log.info("call_llm", symbol=state.symbol)

    budget = get_budget()
    agentic_enabled = os.getenv("ENABLE_AGENTIC_MODE", "true").lower() != "false"

    verdict: StockVerdict
    agentic_used = False

    if agentic_enabled and not budget.is_exhausted():
        try:
            from analyzer.llm.agent import run_agentic_analysis

            verdict = run_agentic_analysis(
                stock=stock,
                tech=tech,
                scoring=scoring,
                news=state.news,
                news_context=state.news_context,
                memory_context=state.memory_context,
            )
            agentic_used = True
        except Exception as e:
            log.warning("agentic_failed_falling_back", symbol=state.symbol, error=str(e))
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
                memory_context=state.memory_context,
            )
    else:
        if budget.is_exhausted():
            log.warning("budget_exhausted_using_fixed_pipeline", symbol=state.symbol)
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
            memory_context=state.memory_context,
        )

    # Task 3.9: schema guardrails
    current_price = stock.current_price if stock else 0.0
    verdict = validate_verdict(verdict, current_price, state.symbol)

    # Task 3.6: consume tokens
    budget.consume(verdict.input_tokens + verdict.output_tokens, label=state.symbol)

    log.info(
        "llm_done",
        symbol=state.symbol,
        signal=verdict.signal,
        confidence=verdict.confidence,
        agentic=agentic_used,
    )
    return state.model_copy(update={"verdict": verdict, "agentic_mode_used": agentic_used})


def node_publish(state: AnalysisState) -> AnalysisState:
    """Save verdict to storage + update Mem0 memory."""
    if state.verdict is None or state.error:
        return state
    log.info("publish", symbol=state.symbol, signal=state.verdict.signal)
    _store.save(state.run_date, state.symbol, state.verdict)

    # Task 3.1: store verdict as episodic memory for future runs
    try:
        _memory.add_verdict(state.symbol, state.run_date, state.verdict)
    except Exception as e:
        log.warning("memory_save_failed", symbol=state.symbol, error=str(e))

    return state


# ── Error routing ─────────────────────────────────────────────────────────────


def _should_continue(state: AnalysisState) -> str:
    return "error" if state.error else "continue"


# ── Graph ─────────────────────────────────────────────────────────────────────


def build_4pm_graph() -> StateGraph[AnalysisState]:
    g = StateGraph(AnalysisState)

    # Phase 3A new nodes
    g.add_node("check_outcomes", node_check_outcomes)
    g.add_node("inject_memory", node_inject_memory)
    g.add_node("validate_frames", node_validate_frames)
    g.add_node("sanitize_inputs", node_sanitize_inputs)
    g.add_node("apply_nemo_rails", node_apply_nemo_rails)
    g.add_node("reflect", node_reflect)
    g.add_node("human_review", node_human_review)

    # Phase 2 nodes
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

    # Full sequence
    g.add_edge(START, "check_outcomes")
    g.add_edge("check_outcomes", "inject_memory")
    g.add_edge("inject_memory", "fetch_data")
    g.add_edge("fetch_data", "fetch_delivery")
    g.add_edge("fetch_delivery", "validate_frames")
    g.add_edge("validate_frames", "compute_technical")
    g.add_edge("compute_technical", "fetch_fundamentals")
    g.add_edge("fetch_fundamentals", "fetch_india")
    g.add_edge("fetch_india", "score_all")
    g.add_edge("score_all", "fetch_news")
    g.add_edge("fetch_news", "sanitize_inputs")
    g.add_edge("sanitize_inputs", "fetch_corporate")
    g.add_edge("fetch_corporate", "fetch_macro")
    g.add_edge("fetch_macro", "call_llm")
    g.add_edge("call_llm", "apply_nemo_rails")
    g.add_edge("apply_nemo_rails", "reflect")
    g.add_edge("reflect", "human_review")
    g.add_edge("human_review", "publish")
    g.add_edge("publish", END)

    return g


def run_4pm(symbol: str) -> AnalysisState:
    """Run the full 4 PM pipeline for a single stock."""
    graph = build_4pm_graph().compile()
    initial = AnalysisState(symbol=symbol)
    result = graph.invoke(initial)
    return AnalysisState(**result)
