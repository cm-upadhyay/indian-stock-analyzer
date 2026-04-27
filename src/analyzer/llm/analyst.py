"""4 PM LLM analyst call — assembles prompt, calls LLM, returns StockVerdict."""

from __future__ import annotations

import json

import structlog

from analyzer.adapters import openai as llm_adapter
from analyzer.data.models import (
    CorporateEvents,
    FundamentalSignals,
    IndiaSignals,
    MacroContext,
    NewsItem,
    ScoringResult,
    StockData,
    StockVerdict,
    TechnicalSignals,
)
from analyzer.llm.prompt_library import PromptLibrary

log = structlog.get_logger()


def _safe_pct(v: float | None) -> str:
    return f"{v * 100:.1f}%" if v is not None else "N/A"


def _safe_num(v: float | None, d: int = 1) -> str:
    return f"{v:.{d}f}" if v is not None else "N/A"


def _build_user_message(
    stock: StockData,
    tech: TechnicalSignals,
    fund: FundamentalSignals,
    india: IndiaSignals,
    scoring: ScoringResult,
    news: list[NewsItem],
    news_context: str,
    corporate: CorporateEvents,
    macro: MacroContext | None,
) -> str:
    lines = [
        f"Stock: {stock.symbol} ({stock.company_name})",
        f"Current price: ₹{stock.current_price:,.0f}",
        f"Beta: {_safe_num(fund.beta, 2)} (stock volatility vs Nifty)",
        "",
        f"COMBINED VERDICT ({scoring.total_votes} indicators, 3 categories equal weight):",
        f"  {scoring.combined_summary}",
        f"  Technical      ({len(tech.votes):2d}): {scoring.tech_summary}",
        f"  Fundamental    ({len(fund.votes):2d}): {scoring.fund_summary}",
        f"  India-specific ({len(india.votes):2d}): {scoring.india_summary}",
        "",
        "Technical context:",
        f"  RSI {tech.rsi:.1f} ({tech.rsi_label})",
        f"  {tech.trend_ma200}",
        f"  Stochastic %K {tech.stoch_k:.1f} vs %D {tech.stoch_d:.1f} · Bollinger at {tech.bb_pct:.0%} of band",
        f"  Volume ratio: {tech.volume_ratio:.1f}x average · MACD: {tech.macd_label}",
        f"  52-week position: {tech.pct_from_low:.0f}% up from year-low ({tech.w52_label})",
        f"  Delivery %: {tech.delivery_label}",
        "",
        "Fundamental context:",
        f"  Revenue growth: {_safe_pct(fund.revenue_growth)} (YoY) · Earnings growth: {_safe_pct(fund.earnings_growth)} (YoY — <5% is flat)",
        f"  EBITDA margin: {_safe_pct(fund.ebitda_margins)} · Net margin: {_safe_pct(fund.profit_margin)} · ROA: {_safe_pct(fund.return_on_assets)}",
        f"  OCF quality: {_safe_num(fund.ocf_quality, 2)} · Free cash flow: {'positive' if fund.free_cashflow and fund.free_cashflow > 0 else 'negative' if fund.free_cashflow and fund.free_cashflow < 0 else 'N/A'}",
        f"  P/E: {_safe_num(fund.trailing_pe)} · PEG: {_safe_num(fund.peg_ratio, 2)} · D/E: {_safe_num(fund.debt_to_equity)}% · Current ratio: {_safe_num(fund.current_ratio, 2)}",
        (
            f"  Interest coverage: {_safe_num(fund.interest_coverage, 1)}x"
            if fund.interest_coverage
            else "  Interest coverage: N/A"
        ),
        (
            f"  Analyst: {fund.analyst_label} ({fund.analyst_count} analysts) · Direction: {fund.analyst_direction_label} · Upside: {fund.analyst_upside:.1f}%"
            if fund.analyst_count and fund.analyst_upside
            else f"  Analyst: {fund.analyst_label or 'N/A'}"
        ),
        "",
        "India-specific:",
        f"  Promoter holding: {_safe_pct(fund.promoter_stake)} · Institutional: {_safe_pct(fund.inst_holding)}",
    ]

    if india.promoter_pledge_pct is not None:
        pp = india.promoter_pledge_pct
        label = (
            "minimal — no stress"
            if pp < 5
            else "HIGH — forced-sell risk"
            if pp > 25
            else "moderate"
        )
        lines.append(f"  Promoter pledge: {pp:.1f}% ({label})")
    else:
        lines.append("  Promoter pledge: unavailable")

    if india.stock_pcr is not None:
        pcr = india.stock_pcr
        label = (
            "bullish — calls > puts"
            if pcr < 0.7
            else "bearish — puts > calls"
            if pcr > 1.2
            else "neutral"
        )
        lines.append(f"  Stock PCR: {pcr:.2f} ({label})")
    else:
        lines.append("  Stock PCR: unavailable")

    lines += ["", "Corporate events:", corporate.context, "", "Recent news:", news_context]

    if macro:
        lines += ["", "Market context (4 PM post-close):", macro.formatted]

    return "\n".join(lines)


def call_analyst(
    stock: StockData,
    tech: TechnicalSignals,
    fund: FundamentalSignals,
    india: IndiaSignals,
    scoring: ScoringResult,
    news: list[NewsItem],
    news_context: str,
    corporate: CorporateEvents,
    macro: MacroContext | None = None,
) -> StockVerdict:
    log.info("call_analyst_start", symbol=stock.symbol)
    system_prompt = PromptLibrary.get("analysis")
    user_message = _build_user_message(
        stock, tech, fund, india, scoring, news, news_context, corporate, macro
    )

    content, input_tok, output_tok = llm_adapter.chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        response_format={"type": "json_object"},
    )
    log.info(
        "call_analyst_done", symbol=stock.symbol, input_tokens=input_tok, output_tokens=output_tok
    )

    try:
        raw = json.loads(content)
    except json.JSONDecodeError as e:
        # Gemini fallback can return plain text when response_format is dropped
        raise ValueError(f"LLM returned non-JSON for {stock.symbol}: {content[:200]}") from e

    _VALID_SIGNALS = {
        "BUY",
        "SELL",
        "HOLD",
        "STRONG BUY",
        "STRONG SELL",
        "LEAN BUY",
        "LEAN SELL",
        "NEUTRAL",
    }
    signal = raw.get("signal", "")
    if signal not in _VALID_SIGNALS:
        raise ValueError(f"LLM returned unexpected signal '{signal}' for {stock.symbol}")

    return StockVerdict(
        signal=signal,
        confidence=float(raw["confidence"]),
        entry=int(raw["entry"]) if raw.get("entry") else None,
        stop_loss=int(raw["stop_loss"]) if raw.get("stop_loss") else None,
        target=int(raw["target"]) if raw.get("target") else None,
        whats_happening=raw.get("whats_happening", ""),
        why_it_matters=raw.get("why_it_matters", ""),
        watch_out_for=raw.get("watch_out_for", ""),
        trader_action=raw.get("trader_action", ""),
        investor_action=raw.get("investor_action", ""),
        input_tokens=input_tok,
        output_tokens=output_tok,
    )
