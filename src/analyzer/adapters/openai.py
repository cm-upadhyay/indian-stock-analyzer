"""All LLM calls live here — routed through LiteLLM for multi-provider fallback.

Primary: gpt-5.4-mini (OpenAI free tier via data-sharing opt-in)
Fallback: gemini/gemini-1.5-flash (Google free tier — 1M tokens/day)
"""

from __future__ import annotations

import litellm
import structlog

from analyzer.utils.reliability import openai_breaker, retry_api

log = structlog.get_logger()

litellm.drop_params = True  # ignore unsupported params per provider

_PRIMARY = "gpt-5.4-mini"
_FALLBACK = "gemini/gemini-1.5-flash"


def chat_completion(
    messages: list[dict[str, object]],
    model: str = _PRIMARY,
    response_format: dict[str, object] | None = None,
    temperature: float = 0.3,
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
