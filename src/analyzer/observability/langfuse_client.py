"""Langfuse client — prompt registry + LLM call tracing.

What this does:
    1. Prompt registry: PromptLibrary.get() tries Langfuse first. If the prompt exists
       in Langfuse with a "production" label, it's returned (with Jinja2 rendering).
       Falls back to local YAML if Langfuse is unreachable or unconfigured.
       Non-engineers can promote a new prompt version in the Langfuse UI without a PR.

    2. Tracing: each LLM generation can be recorded with token counts and metadata.
       This links Langfuse traces to the exact prompt version that produced them —
       so you can see "prompt v2 vs v1 accuracy" over time.

Graceful degradation:
    If LANGFUSE_PUBLIC_KEY is absent or the Langfuse call fails, all functions return
    None / no-op. The pipeline never crashes because of a missing Langfuse key.

Env:
    LANGFUSE_PUBLIC_KEY  — public key from Langfuse cloud (pk-lf-...)
    LANGFUSE_SECRET_KEY  — secret key (sk-lf-...)
    LANGFUSE_HOST        — default https://cloud.langfuse.com (or self-hosted URL)
"""

from __future__ import annotations

import os
from typing import Any

import structlog

log = structlog.get_logger()

_client: Any = None
_init_attempted = False


def _get_client() -> Any:
    global _client, _init_attempted
    if _init_attempted:
        return _client
    _init_attempted = True

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
    if not public_key or not secret_key:
        log.debug("langfuse_disabled", hint="Set LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY")
        return None

    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    try:
        from langfuse import Langfuse

        _client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        log.info("langfuse_initialized", host=host)
        return _client
    except ImportError:
        log.warning("langfuse_not_installed", hint="pip install langfuse")
        return None
    except Exception as e:
        log.warning("langfuse_init_failed", error=str(e))
        return None


def get_prompt(name: str, **variables: object) -> str | None:
    """Fetch the production-tagged prompt from Langfuse and render it.

    Returns the compiled (Jinja2-rendered) prompt string, or None if Langfuse
    is not configured or the prompt doesn't exist there yet.

    The caller (PromptLibrary.get) falls back to local YAML when this returns None.
    """
    client = _get_client()
    if client is None:
        return None
    try:
        prompt_obj = client.get_prompt(name)  # fetches "production"-labelled version
        compiled: str = prompt_obj.compile(**variables)
        log.debug("langfuse_prompt_fetched", name=name)
        return compiled
    except Exception as e:
        log.warning("langfuse_prompt_fetch_failed", name=name, error=str(e))
        return None


def trace_llm_generation(
    name: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    **metadata: object,
) -> None:
    """Record one LLM generation call to Langfuse for cost/quality tracking."""
    client = _get_client()
    if client is None:
        return
    try:
        client.generation(
            name=name,
            model=model,
            usage={"input": input_tokens, "output": output_tokens, "unit": "TOKENS"},
            metadata=metadata,
        )
    except Exception as e:
        log.warning("langfuse_trace_failed", name=name, error=str(e))


def flush() -> None:
    """Flush pending Langfuse events. Call before Lambda/ECS task returns."""
    import contextlib

    client = _get_client()
    if client is None:
        return
    with contextlib.suppress(Exception):
        client.flush()
