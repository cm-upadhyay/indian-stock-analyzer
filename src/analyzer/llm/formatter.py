"""Display rendering — formats verdicts and morning notes for terminal + Telegram."""

from __future__ import annotations

import re

from analyzer.data.models import ScoringResult, StockVerdict

SEP = "━" * 64

# Telegram MarkdownV1 special characters that must be escaped in user-controlled text
_TG_ESCAPE = re.compile(r"([*_`\[\]])")


def _tg_safe(text: str) -> str:
    """Escape Telegram Markdown special chars in text that comes from external sources."""
    return _TG_ESCAPE.sub(r"\\\1", text)


def _to_int(v: int | float | str) -> int:
    """Parse price field robustly — handles int, float, or string like '₹1,345–₹1,375'."""
    if isinstance(v, int | float):
        return int(v)
    nums = re.findall(r"\d+", str(v).replace(",", ""))
    return int(nums[0]) if nums else 0


def format_verdict(
    symbol: str,
    company_name: str,
    current_price: float,
    beta: float | None,
    scoring: ScoringResult,
    verdict: StockVerdict,
) -> str:
    signal_icon = {"BUY": "↑", "SELL": "↓", "HOLD": "→"}.get(verdict.signal, "→")

    beta_str = f"  ·  Beta: {beta:.2f}" if beta else ""
    header = (
        f"{company_name.upper()}  ·  NSE: {symbol.replace('.NS', '')}\n"
        f"₹{current_price:,.0f}  ·  Signal: {verdict.signal} {signal_icon}"
        f"  ·  Confidence: {verdict.confidence:.0%}{beta_str}"
    )

    score_block = (
        f"Score: {scoring.total_buy} buy  ·  {scoring.total_neutral} neutral  ·  "
        f"{scoring.total_sell} sell  ({scoring.total_votes} indicators, 3-way equal weight)\n"
        f"  Technical      ({len([1] * 12):2d}): {scoring.tech_summary}\n"
        f"  Fundamental    ({len([1] * 15):2d}): {scoring.fund_summary}\n"
        f"  India-specific  ({len([1] * 4):2d}): {scoring.india_summary}"
    )

    if verdict.signal == "HOLD" or verdict.entry is None:
        trade = "  No trade. Direction is unclear — wait for a clearer setup."
    else:
        trade = f"  Entry ₹{verdict.entry:,}  ·  Stop ₹{verdict.stop_loss or 0:,}  ·  Target ₹{verdict.target or 0:,}"

    sections = [SEP, header, SEP, score_block, "", trade, "", SEP]

    if verdict.whats_happening:
        sections += ["", "What's Happening", verdict.whats_happening]
    if verdict.why_it_matters:
        sections += ["", "Why It Matters", verdict.why_it_matters]
    if verdict.watch_out_for:
        sections += ["", "Watch Out For", verdict.watch_out_for]

    sections += ["", SEP, ""]

    if verdict.trader_action:
        sections += ["For Traders  (days to weeks)", verdict.trader_action, ""]
    if verdict.investor_action:
        sections += ["For Investors  (months to years)", verdict.investor_action, ""]

    sections.append(SEP)
    return "\n".join(sections)


def format_telegram(
    symbol: str,
    company_name: str,
    current_price: float,
    verdict: StockVerdict,
    scoring: ScoringResult,
) -> str:
    """Compact Telegram-friendly format (no wide ASCII separators)."""
    signal_icon = {"BUY": "↑", "SELL": "↓", "HOLD": "→"}.get(verdict.signal, "→")
    lines = [
        # company_name from yfinance — escape before wrapping in *bold*
        f"*{_tg_safe(company_name)}* (NSE: {symbol.replace('.NS', '')})",
        f"₹{current_price:,.0f}  {verdict.signal} {signal_icon}  {verdict.confidence:.0%} confidence",
        f"Score: {scoring.total_buy}B · {scoring.total_neutral}N · {scoring.total_sell}S  ({scoring.grade})",
    ]
    if verdict.signal != "HOLD" and verdict.entry is not None:
        lines.append(
            f"Entry ₹{verdict.entry:,}  Stop ₹{verdict.stop_loss or 0:,}  Target ₹{verdict.target or 0:,}"
        )
    if verdict.whats_happening:
        # LLM-generated text — escape in case model included markdown chars
        lines += ["", _tg_safe(verdict.whats_happening)]
    if verdict.watch_out_for:
        lines += ["⚠️ " + _tg_safe(verdict.watch_out_for)]
    return "\n".join(lines)
