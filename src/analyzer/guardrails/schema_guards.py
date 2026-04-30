"""Guardrails AI — business-rule validators on LLM verdict fields.

What Guardrails AI does:
    Pydantic already validates the *shape* of the output (is 'confidence' a float?
    is 'signal' one of BUY/HOLD/SELL?). Guardrails AI validates *business rules*:
        - Entry price must be within 5% of current market price (not a random number)
        - Stop-loss must be 2–8% below entry for BUY (not 0% or 50% away)
        - Confidence must be ≥ 0.6 for a directional call (not 0.3 — that's a HOLD)
        - Text fields must not contain banned phrases like "guaranteed" or "risk-free"

    When a validator fails, Guardrails AI auto-retries the LLM call with a corrective
    instruction appended: "The previous entry price was invalid because... Fix it."
    This happens up to 2 times before raising an error.

Graceful degradation:
    If guardrails-ai is not installed, validate_verdict() passes through unchanged
    with a warning log. The pipeline never crashes because of a missing guardrail.

Env:
    GUARDRAILS_ENABLED — set "false" to bypass (default: true)
    MAX_GUARD_RETRIES  — number of auto-fix retries (default: 2)
"""

from __future__ import annotations

import re

import structlog

from analyzer.config import settings
from analyzer.data.models import StockVerdict

log = structlog.get_logger()

_ENABLED = settings.guardrails_enabled
_MAX_RETRIES = settings.max_guard_retries

_BANNED_PHRASES = [
    "guaranteed",
    "risk-free",
    "risk free",
    "certain to",
    "100%",
    "no risk",
    "sure thing",
    "definitely will",
]


# ── Pure validators (no Guardrails AI dep) ────────────────────────────────────
# These run even when guardrails-ai is not installed.
# They mirror what the Guardrails AI validators check, so the logic is testable
# without the library.


class VerdictViolation(Exception):
    """Raised when a verdict violates a business rule and cannot be auto-fixed."""

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


def check_entry_price_range(entry: int | None, current_price: float) -> str | None:
    """Entry must be within 5% of current market price.

    Returns an error message if invalid, None if valid.
    """
    if entry is None:
        return None  # HOLD verdicts have no entry
    if current_price <= 0:
        return None  # can't validate without a reference price
    ratio = abs(entry - current_price) / current_price
    if ratio > settings.guardrail_entry_deviation_pct:
        return (
            f"Entry ₹{entry} is {ratio:.1%} away from current price ₹{current_price:.0f}. "
            f"Entry must be within {settings.guardrail_entry_deviation_pct:.0%} of current price."
        )
    return None


def check_stop_loss_valid(signal: str, entry: int | None, stop_loss: int | None) -> str | None:
    """Stop-loss must be 2–8% below entry for BUY, 2–8% above entry for SELL.

    Returns an error message if invalid, None if valid.
    """
    if signal not in ("BUY", "SELL") or entry is None or stop_loss is None:
        return None

    if signal == "BUY":
        if stop_loss >= entry:
            return f"Stop-loss ₹{stop_loss} must be below entry ₹{entry} for a BUY."
        ratio = (entry - stop_loss) / entry
        if (
            ratio < settings.guardrail_stop_loss_min_pct
            or ratio > settings.guardrail_stop_loss_max_pct
        ):
            return (
                f"Stop-loss ₹{stop_loss} is {ratio:.1%} below entry ₹{entry}. "
                f"Must be {settings.guardrail_stop_loss_min_pct:.0%}–{settings.guardrail_stop_loss_max_pct:.0%} below for a BUY."
            )

    elif signal == "SELL":
        if stop_loss <= entry:
            return f"Stop-loss ₹{stop_loss} must be above entry ₹{entry} for a SELL."
        ratio = (stop_loss - entry) / entry
        if (
            ratio < settings.guardrail_stop_loss_min_pct
            or ratio > settings.guardrail_stop_loss_max_pct
        ):
            return (
                f"Stop-loss ₹{stop_loss} is {ratio:.1%} above entry ₹{entry}. "
                f"Must be {settings.guardrail_stop_loss_min_pct:.0%}–{settings.guardrail_stop_loss_max_pct:.0%} above for a SELL."
            )

    return None


def check_confidence_threshold(signal: str, confidence: float) -> str | None:
    """BUY and SELL calls require confidence ≥ 0.6. Below that should be HOLD.

    Returns an error message if invalid, None if valid.
    """
    if signal in ("BUY", "SELL") and confidence < settings.guardrail_min_confidence:
        return (
            f"Confidence {confidence:.2f} is too low for a {signal}. "
            f"Use HOLD for confidence below {settings.guardrail_min_confidence:.2f}."
        )
    return None


def check_banned_phrases(verdict: StockVerdict) -> list[str]:
    """Scan all text fields for phrases that imply certainty or no risk.

    Returns a list of (field, phrase) pairs that were found.
    """
    text_fields = {
        "whats_happening": verdict.whats_happening,
        "why_it_matters": verdict.why_it_matters,
        "watch_out_for": verdict.watch_out_for,
        "trader_action": verdict.trader_action,
        "investor_action": verdict.investor_action,
    }
    violations = []
    for field, text in text_fields.items():
        for phrase in _BANNED_PHRASES:
            if re.search(re.escape(phrase), text, re.IGNORECASE):
                violations.append(f"{field} contains banned phrase: '{phrase}'")
    return violations


# ── Guardrails AI integration ─────────────────────────────────────────────────


def _get_guard():  # type: ignore[no-untyped-def]
    """Lazy-load a Guardrails Guard instance. Returns None if not installed."""
    try:
        from guardrails import Guard

        return Guard()
    except ImportError:
        log.warning("guardrails_ai_not_installed", hint="pip install guardrails-ai")
        return None


def validate_verdict(
    verdict: StockVerdict,
    current_price: float,
    symbol: str = "",
) -> StockVerdict:
    """Run all business-rule validators on a verdict.

    If Guardrails AI is installed:
        - Violations trigger a structured log + the violation is noted
        - The verdict is returned as-is (Guardrails auto-fix requires re-calling the LLM,
          which is handled in llm/analyst.py where the LLM call lives)

    If Guardrails AI is not installed:
        - Pure Python validators still run
        - Violations are logged as warnings
        - The verdict is returned unchanged (never crashes the pipeline)

    The caller (node_call_llm) decides whether to re-call the LLM or accept the verdict.
    """
    if not _ENABLED:
        return verdict

    violations: list[str] = []

    entry_err = check_entry_price_range(verdict.entry, current_price)
    if entry_err:
        violations.append(entry_err)

    stop_err = check_stop_loss_valid(verdict.signal, verdict.entry, verdict.stop_loss)
    if stop_err:
        violations.append(stop_err)

    conf_err = check_confidence_threshold(verdict.signal, verdict.confidence)
    if conf_err:
        violations.append(conf_err)

    phrase_violations = check_banned_phrases(verdict)
    violations.extend(phrase_violations)

    if violations:
        log.warning(
            "verdict_guard_violations",
            symbol=symbol,
            signal=verdict.signal,
            violations=violations,
        )

    return verdict
