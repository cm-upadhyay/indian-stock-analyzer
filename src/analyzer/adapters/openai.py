"""All LLM calls live here — routed through LiteLLM for multi-provider fallback.

Model tiers (OpenAI free tier via data-sharing opt-in):
  PRIMARY_MODEL — 2.5M tokens/day bucket (mini models). Default: gpt-5.4-mini.
                  Override with LLM_PRIMARY_MODEL env var.
  SMART_MODEL   — 250K tokens/day bucket (full models). Default: gpt-5.
                  Used for reflection reviewer only (fires on ~5-8 stocks/day).
                  Override with LLM_SMART_MODEL env var.
  FALLBACK      — gemini/gemini-1.5-flash (Google free tier — 1M tokens/day).
                  Used automatically when the primary call fails.

To change models without touching code, set env vars in .env or SSM:
  LLM_PRIMARY_MODEL=gpt-5-mini     # switch to a different mini-tier model
  LLM_SMART_MODEL=gpt-5.4          # upgrade reviewer to a newer smart model

Never hardcode model names anywhere else — always import PRIMARY_MODEL / SMART_MODEL
from this module so there is one place to change them.
"""

from __future__ import annotations

import litellm
import structlog

from analyzer.config import settings
from analyzer.utils.reliability import openai_breaker, retry_api

log = structlog.get_logger()

litellm.drop_params = True  # ignore unsupported params per provider

# Re-exported as module-level constants so other modules can import them
# without going through settings directly (backward-compatible API).
PRIMARY_MODEL: str = settings.llm_primary_model
SMART_MODEL: str = settings.llm_smart_model
_FALLBACK: str = settings.llm_fallback_model


def chat_completion(
    messages: list[dict[str, object]],
    model: str = PRIMARY_MODEL,
    response_format: dict[str, object] | None = None,
    temperature: float = settings.llm_temperature,
) -> tuple[str, int, int]:
    """Call LLM, return (content, input_tokens, output_tokens).

    Falls back to Gemini Flash if the primary provider fails.
    """
    kwargs: dict[str, object] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if response_format:
        kwargs["response_format"] = response_format

    def _call() -> object:
        try:
            return litellm.completion(**kwargs)
        except Exception as e:
            log.warning(
                "llm_primary_failed_using_fallback",
                primary=model,
                fallback=_FALLBACK,
                error=str(e),
            )
            kwargs["model"] = _FALLBACK
            kwargs.pop("response_format", None)  # Gemini doesn't support json_object mode
            return litellm.completion(**kwargs)

    resp = openai_breaker(retry_api(_call))()

    content: str = resp.choices[0].message.content or ""
    usage = resp.usage
    used_model = resp.model or kwargs["model"]
    log.info(
        "llm_call_done",
        model=used_model,
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
    )
    return content, usage.prompt_tokens, usage.completion_tokens
