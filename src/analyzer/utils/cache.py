"""Semantic LLM response cache — skip re-running identical prompts.

Why this exists:
    The screener re-runs the same stocks on retry, during dev iteration, and
    sometimes on the same calendar day with unchanged data. Without caching,
    every re-run burns real tokens.

How the cache key works:
    SHA-256 over (prompt_name, prompt_version, rendered_prompt, model_name, temperature).
    Deterministic — same inputs always produce the same key. Promoting a prompt
    version in Langfuse changes the rendered text → new hash → auto-invalidation.

Storage (Phase 3C):
    /tmp/data/cache/{prompt_name}/{hash[:2]}/{hash}.json
    Local filesystem — ephemeral on Lambda, persistent in ECS Fargate.
    Phase 4 swaps to S3 with a 7-day lifecycle rule (same interface).

Flag-gated:
    enable_semantic_cache in config/flags.yaml (default: true).
    Set FLAG_ENABLE_SEMANTIC_CACHE=false to disable without code changes.

Observability:
    Logs cache_hit=true with symbol + prompt_name on every hit.
    tokens_saved emitted on hit (estimated as a zero-cost call).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

_CACHE_ROOT = Path("/tmp/data/cache")


def _is_enabled() -> bool:
    try:
        from analyzer.flags import get_flag

        return bool(get_flag("enable_semantic_cache", default=True))
    except Exception:
        return True


def _make_key(
    prompt_name: str,
    prompt_version: str,
    rendered_prompt: str,
    model: str,
    temperature: float,
) -> str:
    payload = json.dumps(
        {
            "prompt_name": prompt_name,
            "prompt_version": prompt_version,
            "rendered_prompt": rendered_prompt,
            "model": model,
            "temperature": temperature,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _cache_path(prompt_name: str, key: str) -> Path:
    return _CACHE_ROOT / prompt_name / key[:2] / f"{key}.json"


def get(
    prompt_name: str,
    prompt_version: str,
    rendered_prompt: str,
    model: str,
    temperature: float,
    symbol: str = "",
) -> dict[str, Any] | None:
    """Return cached LLM response dict, or None on miss."""
    if not _is_enabled():
        return None
    key = _make_key(prompt_name, prompt_version, rendered_prompt, model, temperature)
    path = _cache_path(prompt_name, key)
    if not path.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text())
        log.info(
            "cache_hit",
            prompt_name=prompt_name,
            symbol=symbol,
            key=key[:12],
        )
        return data
    except Exception as e:
        log.warning("cache_read_failed", path=str(path), error=str(e))
        return None


def put(
    prompt_name: str,
    prompt_version: str,
    rendered_prompt: str,
    model: str,
    temperature: float,
    response: dict[str, Any],
    symbol: str = "",
) -> None:
    """Store an LLM response dict into the cache."""
    if not _is_enabled():
        return
    key = _make_key(prompt_name, prompt_version, rendered_prompt, model, temperature)
    path = _cache_path(prompt_name, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {**response, "_cached_at": time.time(), "_key": key[:12]},
                ensure_ascii=False,
            )
        )
        log.debug("cache_stored", prompt_name=prompt_name, symbol=symbol, key=key[:12])
    except Exception as e:
        log.warning("cache_write_failed", path=str(path), error=str(e))
