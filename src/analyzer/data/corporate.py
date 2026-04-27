"""Fetch corporate events — earnings dates, dividends, stock splits."""

from __future__ import annotations

from datetime import date

import structlog

from analyzer.adapters import yfinance as yf_adapter
from analyzer.data.models import CorporateEvents

log = structlog.get_logger()


def fetch_corporate_events(symbol: str) -> CorporateEvents:
    log.info("fetch_corporate_events", symbol=symbol)
    cal = yf_adapter.get_calendar(symbol)
    divs = yf_adapter.get_dividends(symbol).tail(4)
    actions = yf_adapter.get_actions(symbol)

    lines: list[str] = []

    # Upcoming earnings — pre-earnings = high uncertainty, warrants confidence deduction
    if cal and "Earnings Date" in cal:
        earnings_dates = cal["Earnings Date"]
        if isinstance(earnings_dates, list) and earnings_dates:
            next_earnings = earnings_dates[0]
            days_away = (next_earnings - date.today()).days
            if 0 <= days_away <= 5:
                lines.append(
                    f"EARNINGS IN {days_away} DAYS ({next_earnings}) — results imminent, expect volatility"
                )
            elif 0 < days_away <= 30:
                lines.append(f"Earnings on {next_earnings} ({days_away} days away)")

    # Dividend history — growing/stable/declining tells us about cash generation
    if not divs.empty:
        recent = [(str(d.date()), round(float(v), 2)) for d, v in divs.items()]
        values = [v for _, v in recent]
        trend = (
            "growing"
            if values[-1] > values[0]
            else "declining"
            if values[-1] < values[0]
            else "stable"
        )
        summary = ", ".join(f"Rs.{v} ({d})" for d, v in recent[-3:])
        lines.append(f"Dividend history (last 3): {summary} — trend: {trend}")

    # Upcoming ex-dividend
    ex_div = cal.get("Ex-Dividend Date") if cal else None
    if ex_div:
        days_away = (ex_div - date.today()).days
        if 0 <= days_away <= 30:
            lines.append(f"Ex-dividend date in {days_away} days ({ex_div})")

    # Recent splits — distort all price-based indicators until adjusted
    if "Stock Splits" in actions.columns:
        recent_splits = actions[actions["Stock Splits"] > 0].tail(2)
        if not recent_splits.empty:
            for d, row in recent_splits.iterrows():
                lines.append(
                    f"Stock split {int(row['Stock Splits'])}:1 on {d.date()} — indicators adjusted"
                )

    context = (
        "\n".join(f"- {line}" for line in lines) if lines else "- No upcoming corporate events"
    )
    return CorporateEvents(lines=lines, context=context)
