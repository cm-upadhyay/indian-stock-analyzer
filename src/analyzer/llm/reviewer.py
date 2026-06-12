"""Reflection — a smarter model reviews uncertain verdicts before publishing.

What reflection does:
    The primary analyst (LLM_PRIMARY_MODEL, 2.5M token/day bucket) produces a verdict
    for every stock. For verdicts that look uncertain, a smarter reviewer
    (LLM_SMART_MODEL, 250K token/day bucket) is called with the question:
    "Does this verdict make sense given the data?"

    The reviewer checks:
        1. Does the signal match the technical and fundamental data?
        2. Is the stop-loss reasonable given the stock's volatility?
        3. Does the news sentiment contradict the signal?
        4. Are there any obvious errors in the price targets?

    If the reviewer disagrees, it can:
        - Override the signal (BUY → HOLD)
        - Adjust the confidence
        - Add a note to watch_out_for

Smart trigger (saves tokens):
    Reflection only fires when ALL of the following are true:
        - Signal is BUY or SELL (not HOLD — HOLD doesn't need review)
        - Confidence < REFLECTION_CONFIDENCE_THRESHOLD (default 0.65)
        - OR news_sentiment contradicts the signal

    This means reflection fires for ~20-30% of stocks, not all 30.
    At ~3K tokens per reflection call × 30% × 30 stocks = ~27K tokens/day.

Env:
    ENABLE_REFLECTION                — "true"/"false" (default: true)
    REFLECTION_CONFIDENCE_THRESHOLD  — float 0–1 (default: 0.65)
    REVIEWER_MODEL                   — reviewer model (default: LLM_SMART_MODEL)
    LLM_SMART_MODEL                  — smart model (default: gpt-5)
    LLM_PRIMARY_MODEL                — primary model (default: gpt-5.4-mini)
"""

from __future__ import annotations

import json

import structlog

from analyzer.adapters import openai as llm_adapter
from analyzer.adapters.openai import SMART_MODEL
from analyzer.config import settings
from analyzer.data.models import StockVerdict, TechnicalSignals
from analyzer.llm.prompt_library import PromptLibrary

log = structlog.get_logger()

_ENABLED = settings.enable_reflection
_REVIEWER_MODEL = settings.reviewer_model or SMART_MODEL
_CONFIDENCE_THRESHOLD = settings.reflection_confidence_threshold


def should_reflect(
    verdict: StockVerdict,
    tech: TechnicalSignals | None = None,
    news_context: str = "",
) -> bool:
    """Decide whether reflection is needed for this verdict.

    Returns True only when it's worth the token cost.
    HOLD verdicts are never reflected — they don't need a second opinion.
    """
    if not _ENABLED:
        return False

    if verdict.signal == "HOLD":
        return False  # HOLD = "not sure", no need to double-check "not sure"

    # Low confidence directional calls are the main trigger
    if verdict.confidence < _CONFIDENCE_THRESHOLD:
        log.info(
            "reflect_trigger_low_confidence",
            signal=verdict.signal,
            confidence=verdict.confidence,
        )
        return True

    # News contradicts signal: BUY signal but news mentions "loss", "fraud", "recall"
    negative_keywords = [
        "loss",
        "fraud",
        "penalty",
        "recall",
        "insolvency",
        "default",
        "sebi notice",
    ]
    positive_keywords = ["profit", "order win", "expansion", "dividend", "buyback", "upgrade"]

    news_lower = news_context.lower()

    if verdict.signal == "BUY" and any(k in news_lower for k in negative_keywords):
        log.info("reflect_trigger_news_contradicts_buy")
        return True

    if verdict.signal == "SELL" and any(k in news_lower for k in positive_keywords):
        log.info("reflect_trigger_news_contradicts_sell")
        return True

    return False


def call_reviewer(
    symbol: str,
    verdict: StockVerdict,
    user_message_summary: str,
    current_price: float,
) -> tuple[StockVerdict, bool]:
    """Call the reviewer model and return (final_verdict, was_overridden).

    The reviewer reads the full user message context (same data the analyst saw)
    plus the analyst's verdict, and produces either:
        - A confirmation ("I agree with this verdict")
        - An override ("The signal should be HOLD, not BUY, because...")

    Returns:
        verdict:       the final verdict (may be same as input or modified)
        was_overridden: True if the reviewer changed the signal or confidence
    """
    log.info("reviewer_start", symbol=symbol, model=_REVIEWER_MODEL)

    system_prompt = PromptLibrary.get("reflection")

    entry_line = f"₹{verdict.entry:,}" if verdict.entry else "N/A (HOLD)"
    stop_line = f"₹{verdict.stop_loss:,}" if verdict.stop_loss else "N/A"
    target_line = f"₹{verdict.target:,}" if verdict.target else "N/A"
    reviewer_user_message = (
        f"ORIGINAL ANALYSIS DATA:\n{user_message_summary}\n\n"
        f"PRIMARY ANALYST VERDICT:\n"
        f"  Signal:     {verdict.signal}\n"
        f"  Confidence: {verdict.confidence:.0%}\n"
        f"  Entry:      {entry_line}\n"
        f"  Stop-loss:  {stop_line}\n"
        f"  Target:     {target_line}\n"
        f"  Watch out:  {verdict.watch_out_for}\n\n"
        f"Current market price: ₹{current_price:,.0f}\n\n"
        f"Review this verdict. Output JSON with fields:\n"
        f"  agree (bool), override_signal (str or null), override_confidence (float or null),\n"
        f"  reviewer_note (str — one sentence explaining your decision)"
    )

    try:
        content, in_tok, out_tok = llm_adapter.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": reviewer_user_message},
            ],
            model=_REVIEWER_MODEL,
            response_format={"type": "json_object"},
        )
        log.info(
            "reviewer_done",
            symbol=symbol,
            input_tokens=in_tok,
            output_tokens=out_tok,
        )
    except Exception as e:
        log.error("reviewer_failed", symbol=symbol, error=str(e))
        return verdict, False

    try:
        review = json.loads(content)
    except json.JSONDecodeError:
        log.warning("reviewer_non_json", symbol=symbol, content=content[:200])
        return verdict, False

    agreed = bool(review.get("agree", True))
    reviewer_note = str(review.get("reviewer_note", ""))

    if agreed:
        log.info("reviewer_agreed", symbol=symbol, note=reviewer_note)
        # Append reviewer note to watch_out_for for transparency
        enriched_watch = verdict.watch_out_for
        if reviewer_note:
            enriched_watch = f"{verdict.watch_out_for} [Reviewed: {reviewer_note}]"
        return verdict.model_copy(update={"watch_out_for": enriched_watch}), False

    # Reviewer disagrees — apply overrides
    override_signal = review.get("override_signal")
    override_confidence = review.get("override_confidence")

    updates: dict[str, object] = {}
    was_overridden = False

    if override_signal and override_signal != verdict.signal:
        log.info(
            "reviewer_override_signal",
            symbol=symbol,
            from_signal=verdict.signal,
            to_signal=override_signal,
        )
        updates["signal"] = override_signal
        # If overriding to HOLD, clear price targets
        if override_signal == "HOLD":
            updates["entry"] = None
            updates["stop_loss"] = None
            updates["target"] = None
        was_overridden = True

    if override_confidence is not None:
        updates["confidence"] = float(override_confidence)
        was_overridden = True

    if reviewer_note:
        updates["watch_out_for"] = f"{verdict.watch_out_for} [Reviewer override: {reviewer_note}]"

    final_verdict = verdict.model_copy(update=updates) if updates else verdict
    return final_verdict, was_overridden
