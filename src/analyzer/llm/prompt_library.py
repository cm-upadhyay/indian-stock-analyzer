"""PromptLibrary — loads versioned prompts from YAML, renders via Jinja2.

Usage:
    from analyzer.llm.prompt_library import PromptLibrary
    system_prompt = PromptLibrary.get("analysis")
    morning_prompt = PromptLibrary.get("morning", signal="BUY")
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TypedDict

import yaml
from jinja2 import Environment, StrictUndefined

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_ENV_PINS_KEY = "PROMPT_VERSION_{name}"

# Fallback versions if no env pin is set
_DEFAULT_VERSIONS: dict[str, str] = {
    "analysis": "v1",
    "morning": "v1",
    "reflection": "v1",  # Phase 3A — reviewer prompt
}


class PromptTemplate(TypedDict):
    system: str


class PromptLibrary:
    _cache: dict[str, PromptTemplate] = {}

    @classmethod
    def get(cls, name: str, **variables: object) -> str:
        """Return rendered system prompt. Tries Langfuse registry first, falls back to local YAML.

        Langfuse path (Phase 3B — requires LANGFUSE_PUBLIC_KEY):
            Fetches the "production"-labelled prompt version from Langfuse cloud.
            Non-engineers can promote a new version in the Langfuse UI without a PR.
            Falls back to local YAML if Langfuse is unconfigured or unreachable.

        Local YAML path (always available, no network dependency):
            Reads from src/analyzer/llm/prompts/{name}_{version}.yaml.
            Version pinned by PROMPT_VERSION_{NAME} env var (default: v1).
        """
        # Phase 3B: try Langfuse prompt registry first
        try:
            from analyzer.observability.langfuse_client import get_prompt as langfuse_get

            result: str | None = langfuse_get(name, **variables)
            if result is not None:
                return result
        except Exception:
            pass  # any failure falls through to local YAML

        # Fall back to local YAML (always available)
        version = os.getenv(
            _ENV_PINS_KEY.format(name=name.upper()),
            _DEFAULT_VERSIONS.get(name, "v1"),
        )
        cache_key = f"{name}_{version}"
        if cache_key not in cls._cache:
            path = _PROMPTS_DIR / f"{name}_{version}.yaml"
            with open(path) as f:
                loaded: Any = yaml.safe_load(f)

            if not isinstance(loaded, dict):
                raise ValueError(f"Prompt file has invalid structure: {path}")

            system = loaded.get("system")
            if not isinstance(system, str):
                raise ValueError(f"Prompt file is missing string 'system' key: {path}")

            cls._cache[cache_key] = {"system": system}

        raw_system = cls._cache[cache_key]["system"]

        if variables:
            env = Environment(undefined=StrictUndefined)  # nosec B701 # nosemgrep: python.jinja2.security.audit.missing-autoescape-disabled.missing-autoescape-disabled
            raw_system = env.from_string(raw_system).render(**variables)

        return raw_system
