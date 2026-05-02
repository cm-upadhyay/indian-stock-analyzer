"""NeMo Guardrails — system-level policy enforcement via Colang flows.

How NeMo works:
    NeMo Guardrails loads a set of "rails" — rules written in a language called Colang.
    When you pass text through NeMo, it checks whether the text matches any of the
    defined patterns. If it matches a blocked pattern, NeMo returns a safe refusal
    instead of the original text. If nothing matches, the text passes through unchanged.

    Think of it like: Guardrails AI checks individual fields ("is the stop-loss valid?"),
    NeMo checks the whole message ("does this recommend a non-NSE stock?").

Two usage points in the pipeline:
    1. apply_input_rail(news_text) — called in node_sanitize_inputs
       Checks news snippets for adversarial patterns before they enter the LLM prompt.

    2. apply_output_rail(verdict_text) — called after node_call_llm
       Checks the formatted verdict for policy violations before publishing.

Graceful degradation:
    If nemoguardrails is not installed, both functions pass through unchanged with
    a one-time warning. The pipeline never crashes because of a missing rail.

Flag:
    nemo_rails_enabled in config/flags.yaml (default: true).
    Override per-run: FLAG_NEMO_RAILS_ENABLED=false
"""

from __future__ import annotations

from pathlib import Path

import structlog

from analyzer.flags import get_flag

log = structlog.get_logger()

# _ENABLED is intentionally not a module-level constant — get_flag() is per-call
# so flags.yaml changes take effect on the next pipeline run without a redeploy.
_CONFIG_PATH = Path(__file__).parent / "config"

_rails_instance = None
_rails_tried = False


def _get_rails():  # type: ignore[no-untyped-def]
    """Lazy-load NeMo Rails instance (expensive first load, cached after)."""
    global _rails_instance, _rails_tried
    if _rails_tried:
        return _rails_instance
    _rails_tried = True

    try:
        from nemoguardrails import LLMRails, RailsConfig

        config = RailsConfig.from_path(str(_CONFIG_PATH))
        _rails_instance = LLMRails(config)
        log.info("nemo_rails_loaded", config_path=str(_CONFIG_PATH))
        return _rails_instance
    except ImportError:
        log.warning("nemoguardrails_not_installed", hint="pip install nemoguardrails")
        return None
    except Exception as e:
        log.warning("nemo_rails_init_failed", error=str(e))
        return None


def apply_input_rail(text: str, symbol: str = "") -> tuple[str, bool]:
    """Run the input rail on a piece of external content (news snippet, Tavily result).

    Returns:
        (text, blocked): text is the original or a safe placeholder;
                         blocked=True means the rail fired and replaced the content.

    Called from: node_sanitize_inputs in graph_4pm.py
    """
    if not get_flag("nemo_rails_enabled", default=True) or not text.strip():
        return text, False

    rails = _get_rails()  # type: ignore[no-untyped-call]
    if rails is None:
        return text, False

    try:
        # NeMo's generate() takes a message and returns either the text (passed)
        # or a guardrail refusal message (blocked)
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            rails.generate_async(messages=[{"role": "user", "content": text}])
        )

        # If NeMo blocked the content, it returns one of our bot refusal messages
        blocked_markers = [
            "detected a potential prompt injection",
            "blocked",
        ]
        result_text = result.get("content", "") if isinstance(result, dict) else result
        blocked = any(marker in result_text.lower() for marker in blocked_markers)

        if blocked:
            log.warning("nemo_input_rail_blocked", symbol=symbol, text_preview=text[:80])
            return f"[CONTENT BLOCKED BY POLICY RAIL: {result_text}]", True

        return text, False

    except Exception as e:
        log.warning("nemo_input_rail_error", symbol=symbol, error=str(e))
        return text, False


def apply_output_rail(verdict_text: str, symbol: str = "") -> tuple[str, bool]:
    """Run the output rail on a formatted verdict text.

    Returns:
        (verdict_text, blocked): blocked=True means the output was policy-violating.
        If blocked, the verdict should NOT be published.

    Called from: node_apply_nemo_rails in graph_4pm.py
    """
    if not get_flag("nemo_rails_enabled", default=True) or not verdict_text.strip():
        return verdict_text, False

    rails = _get_rails()  # type: ignore[no-untyped-call]
    if rails is None:
        return verdict_text, False

    try:
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            rails.generate_async(messages=[{"role": "assistant", "content": verdict_text}])
        )

        blocked_markers = [
            "blocked",
            "policy violation",
            "only provides verdicts for nse",
        ]
        result_text = result.get("content", "") if isinstance(result, dict) else result
        blocked = any(marker in result_text.lower() for marker in blocked_markers)

        if blocked:
            log.warning(
                "nemo_output_rail_blocked", symbol=symbol, verdict_preview=verdict_text[:80]
            )

        return verdict_text, blocked

    except Exception as e:
        log.warning("nemo_output_rail_error", symbol=symbol, error=str(e))
        return verdict_text, False


def check_symbol_is_nse(symbol: str) -> bool:
    """Return True if symbol looks like a valid NSE-listed equity.

    Pure Python check — no NeMo dep. Used by tests and as a lightweight
    pre-flight before making any data fetch or analysis call.
    RELIANCE.NS → True   |   AAPL → False   |   BTC-USD → False
    """
    import re

    cleaned = symbol.strip().upper()
    # NSE format: uppercase letters/digits/& up to 20 chars, ending in .NS
    return bool(re.match(r"^[A-Z0-9&]{1,20}\.NS$", cleaned))
