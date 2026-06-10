"""Display rendering — formats verdicts and morning notes for terminal + Telegram + email."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from analyzer.data.models import MorningNote, ScoringResult, StockVerdict

SEP = "━" * 64

# Telegram MarkdownV1 special characters that must be escaped in user-controlled text
_TG_ESCAPE = re.compile(r"([*_`\[\]])")

_SIGNAL_COLOR = {"BUY": "#16a34a", "SELL": "#dc2626", "HOLD": "#6b7280"}
_SIGNAL_BG = {"BUY": "#f0fdf4", "SELL": "#fef2f2", "HOLD": "#f9fafb"}
_SIGNAL_ICON = {"BUY": "↑", "SELL": "↓", "HOLD": "→"}
_STATUS_ICON = {"INTACT": "✅", "STRENGTHENED": "🟢", "WEAKENED": "⚠️"}


def _tg_safe(text: str) -> str:
    return _TG_ESCAPE.sub(r"\\\1", text)


def _to_int(v: int | float | str) -> int:
    if isinstance(v, int | float):
        return int(v)
    nums = re.findall(r"\d+", str(v).replace(",", ""))
    return int(nums[0]) if nums else 0


def _h(text: str, color: str = "#1a1a2e", size: str = "15px", margin_top: str = "18px") -> str:
    return f'<p style="margin:{margin_top} 0 4px 0;font-size:{size};font-weight:bold;color:{color};">{text}</p>'


def _p(text: str) -> str:
    return f'<p style="margin:0;font-size:14px;color:#444;line-height:1.65;">{text}</p>'


def _badge(signal: str) -> str:
    color = _SIGNAL_COLOR.get(signal, "#6b7280")
    icon = _SIGNAL_ICON.get(signal, "→")
    return (
        f'<span style="background:{color};color:white;padding:3px 10px;'
        f'border-radius:12px;font-size:12px;font-weight:bold;">{signal} {icon}</span>'
    )


# ── Terminal format (unchanged) ───────────────────────────────────────────────


def format_verdict(
    symbol: str,
    company_name: str,
    current_price: float,
    beta: float | None,
    scoring: ScoringResult,
    verdict: StockVerdict,
) -> str:
    signal_icon = _SIGNAL_ICON.get(verdict.signal, "→")
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


# ── Telegram — evening verdict ────────────────────────────────────────────────


def format_telegram(
    symbol: str,
    company_name: str,
    current_price: float,
    verdict: StockVerdict,
    scoring: ScoringResult,
) -> str:
    signal_icon = _SIGNAL_ICON.get(verdict.signal, "→")
    lines = [
        f"*{_tg_safe(company_name)}* (NSE: {symbol.replace('.NS', '')})",
        f"₹{current_price:,.0f}  {verdict.signal} {signal_icon}  {verdict.confidence:.0%} confidence",
        f"Score: {scoring.total_buy}B · {scoring.total_neutral}N · {scoring.total_sell}S  ({scoring.grade})",
    ]
    if verdict.signal != "HOLD" and verdict.entry is not None:
        lines.append(
            f"Entry ₹{verdict.entry:,}  Stop ₹{verdict.stop_loss or 0:,}  Target ₹{verdict.target or 0:,}"
        )
    if verdict.whats_happening:
        lines += ["", _tg_safe(verdict.whats_happening)]
    if verdict.watch_out_for:
        lines += ["", "⚠️ " + _tg_safe(verdict.watch_out_for)]
    lines += ["", "_Full analysis with trader & investor action in today's email_"]
    return "\n".join(lines)


# ── Telegram — morning note ───────────────────────────────────────────────────


def format_telegram_morning(note: MorningNote) -> str:
    status_icon = _STATUS_ICON.get(note.status, "•")
    signal_icon = _SIGNAL_ICON.get(note.previous_signal, "→")
    lines = [
        f"*{_tg_safe(note.company_name)}* (NSE: {note.symbol.replace('.NS', '')})",
        f"Yesterday: {note.previous_signal} {signal_icon}  |  {status_icon} {note.status}",
        "",
        _tg_safe(note.morning_text),
    ]
    return "\n".join(lines)


# ── HTML email — evening (one email, all stocks) ──────────────────────────────


def format_email_html(
    stocks: list[dict[str, Any]],
    today: date,
    unsubscribe_url: str = "",
) -> str:
    buy = [s for s in stocks if s["verdict"].signal == "BUY"]
    hold = [s for s in stocks if s["verdict"].signal == "HOLD"]
    sell = [s for s in stocks if s["verdict"].signal == "SELL"]
    date_str = today.strftime("%d %b %Y")

    def summary_row(s: dict[str, Any], bg: str) -> str:
        v = s["verdict"]
        symbol = s["symbol"].replace(".NS", "")
        trade = (
            f"Entry ₹{v.entry:,}  Stop ₹{v.stop_loss or 0:,}  Target ₹{v.target or 0:,}"
            if v.entry
            else "—"
        )
        return (
            f'<tr style="background:{bg};">'
            f'<td style="padding:8px 10px;font-size:13px;font-weight:bold;">{s["company_name"]}</td>'
            f'<td style="padding:8px 10px;font-size:12px;color:#555;">{symbol}</td>'
            f'<td style="padding:8px 10px;text-align:center;">{_badge(v.signal)}</td>'
            f'<td style="padding:8px 10px;font-size:13px;text-align:center;">{v.confidence:.0%}</td>'
            f'<td style="padding:8px 10px;font-size:12px;color:#555;">{trade}</td>'
            f"</tr>"
        )

    def summary_group(label: str, group: list[dict[str, Any]], color: str) -> str:
        if not group:
            return ""
        rows = "".join(
            summary_row(s, "#ffffff" if i % 2 == 0 else "#fafafa") for i, s in enumerate(group)
        )
        return (
            f'<tr><td colspan="5" style="padding:10px 10px 4px;font-size:13px;'
            f'font-weight:bold;color:{color};border-top:2px solid {color};">{label}</td></tr>'
            + rows
        )

    def stock_card(s: dict[str, Any]) -> str:
        v: StockVerdict = s["verdict"]
        sc: ScoringResult = s["scoring"]
        symbol = s["symbol"].replace(".NS", "")
        color = _SIGNAL_COLOR.get(v.signal, "#6b7280")
        bg = _SIGNAL_BG.get(v.signal, "#f9fafb")
        beta_str = f" · Beta {s['beta']:.2f}" if s.get("beta") else ""

        trade_block = ""
        if v.signal != "HOLD" and v.entry:
            trade_block = (
                f'<div style="background:{bg};border-left:3px solid {color};'
                f'padding:10px 14px;margin:14px 0;font-size:14px;color:#333;">'
                f"Entry ₹{v.entry:,} &nbsp;|&nbsp; Stop ₹{v.stop_loss or 0:,} &nbsp;|&nbsp; Target ₹{v.target or 0:,}"
                f"</div>"
            )
        else:
            trade_block = (
                '<div style="background:#f9fafb;border-left:3px solid #9ca3af;'
                'padding:10px 14px;margin:14px 0;font-size:14px;color:#6b7280;">'
                "No trade — direction unclear, wait for a clearer setup."
                "</div>"
            )

        sections = ""
        if v.whats_happening:
            sections += _h("What's Happening") + _p(v.whats_happening)
        if v.why_it_matters:
            sections += _h("Why It Matters") + _p(v.why_it_matters)
        if v.watch_out_for:
            sections += _h("⚠️ Watch Out For", color="#b45309") + _p(v.watch_out_for)

        action_block = ""
        if v.trader_action or v.investor_action:
            trader_html = (
                f'<td style="width:50%;padding:12px;background:#eff6ff;vertical-align:top;">'
                f'<p style="margin:0 0 6px;font-size:13px;font-weight:bold;color:#1d4ed8;">For Traders (days to weeks)</p>'
                f'<p style="margin:0;font-size:13px;color:#444;line-height:1.6;">{v.trader_action or ""}</p>'
                f"</td>"
            )
            investor_html = (
                f'<td style="width:50%;padding:12px;background:#fafafa;vertical-align:top;">'
                f'<p style="margin:0 0 6px;font-size:13px;font-weight:bold;color:#374151;">For Investors (months to years)</p>'
                f'<p style="margin:0;font-size:13px;color:#444;line-height:1.6;">{v.investor_action or ""}</p>'
                f"</td>"
            )
            action_block = (
                f'<table style="width:100%;border-collapse:collapse;margin-top:16px;">'
                f"<tr>{trader_html}{investor_html}</tr>"
                f"</table>"
            )

        return (
            f'<div style="background:white;border:1px solid #e5e7eb;border-radius:6px;'
            f'padding:20px;margin-bottom:12px;">'
            f'<table style="width:100%;border-collapse:collapse;">'
            f"<tr>"
            f'<td style="vertical-align:top;">'
            f'<p style="margin:0;font-size:17px;font-weight:bold;color:#1a1a2e;">{s["company_name"]}</p>'
            f'<p style="margin:3px 0 0;font-size:12px;color:#6b7280;">NSE: {symbol} · ₹{s["current_price"]:,.0f}{beta_str}</p>'
            f"</td>"
            f'<td style="text-align:right;vertical-align:top;">'
            f"{_badge(v.signal)}"
            f'<p style="margin:4px 0 0;font-size:12px;color:#6b7280;text-align:right;">{v.confidence:.0%} confidence</p>'
            f"</td>"
            f"</tr>"
            f"</table>"
            f'<div style="background:#f8f8f8;border-radius:4px;padding:10px 12px;margin:14px 0;font-size:13px;color:#444;">'
            f"Score: <strong>{sc.total_buy}B · {sc.total_neutral}N · {sc.total_sell}S</strong> &nbsp;({sc.grade})<br>"
            f'<span style="color:#6b7280;">Technical ({sc.tech_buy + sc.tech_neutral + sc.tech_sell}): '
            f"{sc.tech_buy}B · {sc.tech_neutral}N · {sc.tech_sell}S &nbsp;{sc.tech_summary.split()[0]}<br>"
            f"Fundamental ({sc.fund_buy + sc.fund_neutral + sc.fund_sell}): "
            f"{sc.fund_buy}B · {sc.fund_neutral}N · {sc.fund_sell}S &nbsp;{sc.fund_summary.split()[0]}<br>"
            f"India-specific ({sc.india_buy + sc.india_neutral + sc.india_sell}): "
            f"{sc.india_buy}B · {sc.india_neutral}N · {sc.india_sell}S &nbsp;{sc.india_summary.split()[0]}</span>"
            f"</div>" + trade_block + sections + action_block + "</div>"
        )

    ordered = buy + hold + sell
    cards = "".join(stock_card(s) for s in ordered)

    summary_table = (
        '<table style="width:100%;border-collapse:collapse;font-family:Arial,sans-serif;">'
        + summary_group(f"BUY ({len(buy)})", buy, "#16a34a")
        + summary_group(f"HOLD ({len(hold)})", hold, "#6b7280")
        + summary_group(f"SELL ({len(sell)})", sell, "#dc2626")
        + "</table>"
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:20px;background:#f3f4f6;font-family:Arial,sans-serif;">
<div style="max-width:720px;margin:0 auto;">

  <div style="background:#1a1a2e;color:white;padding:24px;border-radius:8px 8px 0 0;">
    <p style="margin:0;font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;">Indian Stock Analyzer</p>
    <h1 style="margin:6px 0 0;font-size:22px;">{date_str} · Evening Analysis</h1>
    <p style="margin:12px 0 0;">
      <span style="background:#16a34a;color:white;padding:3px 12px;border-radius:12px;font-size:13px;margin-right:6px;">{len(buy)} BUY</span>
      <span style="background:#6b7280;color:white;padding:3px 12px;border-radius:12px;font-size:13px;margin-right:6px;">{len(hold)} HOLD</span>
      <span style="background:#dc2626;color:white;padding:3px 12px;border-radius:12px;font-size:13px;">{len(sell)} SELL</span>
    </p>
  </div>

  <div style="background:white;padding:20px;margin-top:2px;">
    <p style="margin:0 0 12px;font-size:15px;font-weight:bold;color:#1a1a2e;">Quick Summary</p>
    {summary_table}
  </div>

  <div style="margin-top:16px;">
    <p style="margin:0 0 12px;font-size:15px;font-weight:bold;color:#1a1a2e;">Full Analysis</p>
    {cards}
  </div>

  <p style="text-align:center;font-size:11px;color:#9ca3af;margin-top:20px;">
    Indian Stock Analyzer · Not financial advice · For informational purposes only
    {('<br><a href="' + unsubscribe_url + '" style="color:#9ca3af;">Unsubscribe from Pro emails</a>') if unsubscribe_url else ""}
  </p>
</div>
</body></html>"""


# ── HTML email — morning follow-up ────────────────────────────────────────────


def format_morning_email_html(
    notes: list[MorningNote], today: date, unsubscribe_url: str = ""
) -> str:
    date_str = today.strftime("%d %b %Y")
    intact = [n for n in notes if n.status == "INTACT"]
    strengthened = [n for n in notes if n.status == "STRENGTHENED"]
    weakened = [n for n in notes if n.status == "WEAKENED"]

    def note_row(n: MorningNote, bg: str) -> str:
        status_icon = _STATUS_ICON.get(n.status, "•")
        status_color = {"INTACT": "#16a34a", "STRENGTHENED": "#1d4ed8", "WEAKENED": "#b45309"}.get(
            n.status, "#6b7280"
        )
        return (
            f'<tr style="background:{bg};">'
            f'<td style="padding:10px 12px;font-size:13px;font-weight:bold;">{n.company_name}</td>'
            f'<td style="padding:10px 12px;font-size:12px;color:#6b7280;">{n.symbol.replace(".NS", "")}</td>'
            f'<td style="padding:10px 12px;text-align:center;">{_badge(n.previous_signal)}</td>'
            f'<td style="padding:10px 12px;font-size:13px;font-weight:bold;color:{status_color};">{status_icon} {n.status}</td>'
            f'<td style="padding:10px 12px;font-size:12px;color:#555;line-height:1.5;">{n.morning_text}</td>'
            f"</tr>"
        )

    def group_rows(label: str, group: list[MorningNote], color: str) -> str:
        if not group:
            return ""
        rows = "".join(
            note_row(n, "#ffffff" if i % 2 == 0 else "#fafafa") for i, n in enumerate(group)
        )
        return (
            f'<tr><td colspan="5" style="padding:10px 10px 4px;font-size:13px;'
            f'font-weight:bold;color:{color};border-top:2px solid {color};">{label} ({len(group)})</td></tr>'
            + rows
        )

    table = (
        '<table style="width:100%;border-collapse:collapse;font-size:13px;">'
        + group_rows("INTACT", intact, "#16a34a")
        + group_rows("STRENGTHENED", strengthened, "#1d4ed8")
        + group_rows("WEAKENED", weakened, "#b45309")
        + "</table>"
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:20px;background:#f3f4f6;font-family:Arial,sans-serif;">
<div style="max-width:720px;margin:0 auto;">

  <div style="background:#1a1a2e;color:white;padding:24px;border-radius:8px 8px 0 0;">
    <p style="margin:0;font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;">Indian Stock Analyzer · Morning Follow-up</p>
    <h1 style="margin:6px 0 0;font-size:22px;">{date_str} · How are yesterday's calls holding?</h1>
    <p style="margin:12px 0 0;">
      <span style="background:#16a34a;color:white;padding:3px 12px;border-radius:12px;font-size:13px;margin-right:6px;">✅ {len(intact)} Intact</span>
      <span style="background:#1d4ed8;color:white;padding:3px 12px;border-radius:12px;font-size:13px;margin-right:6px;">🟢 {len(strengthened)} Strengthened</span>
      <span style="background:#b45309;color:white;padding:3px 12px;border-radius:12px;font-size:13px;">⚠️ {len(weakened)} Weakened</span>
    </p>
  </div>

  <div style="background:white;padding:20px;margin-top:2px;border-radius:0 0 8px 8px;">
    <p style="margin:0 0 14px;font-size:13px;color:#6b7280;">
      This is a pre-market follow-up on yesterday's signals — not new analysis.
      Full analysis runs at 4:30 PM after market close.
    </p>
    {table}
  </div>

  <p style="text-align:center;font-size:11px;color:#9ca3af;margin-top:20px;">
    Indian Stock Analyzer · Not financial advice · For informational purposes only
    {('<br><a href="' + unsubscribe_url + '" style="color:#9ca3af;">Unsubscribe from Pro emails</a>') if unsubscribe_url else ""}
  </p>
</div>
</body></html>"""
