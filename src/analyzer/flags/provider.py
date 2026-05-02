"""OpenFeature-compatible flag provider backed by config/flags.yaml.

Architecture:
    - Reads config/flags.yaml on first call (lazy load + cached)
    - Env var override: FLAG_ENABLE_REFLECTION=true overrides any YAML value
    - Falls back to settings.py defaults so existing code keeps working if
      flags.yaml is missing (graceful degradation during migration)
    - Phase 4 swaps this module's internals for an OpenFeature Flipt provider;
      all call sites (get_flag / get_string_flag) stay unchanged

Flag file location:
    Resolved relative to the repo root (3 directories up from this file).
    Works both locally and inside the Docker containers (COPY config/ /app/config/).

Env var override convention:
    FLAG_<UPPER_SNAKE_FLAG_NAME>=true|false
    e.g. FLAG_ENABLE_HITL=true, FLAG_KILL_SWITCH_PUBLISH_VERDICTS=false
"""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock
from typing import Any

import structlog
import yaml

log = structlog.get_logger()

_FLAGS_PATH = Path(__file__).parents[3] / "config" / "flags.yaml"
_lock = Lock()
_loaded: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _loaded
    if _loaded is not None:
        return _loaded
    with _lock:
        if _loaded is not None:
            return _loaded
        if _FLAGS_PATH.exists():
            with open(_FLAGS_PATH) as f:
                raw: Any = yaml.safe_load(f) or {}
            bools: dict[str, bool] = {k: bool(v) for k, v in raw.get("flags", {}).items()}
            strings: dict[str, str] = {k: str(v) for k, v in raw.get("strings", {}).items()}
            _loaded = {"flags": bools, "strings": strings}
            log.debug("flags_loaded", path=str(_FLAGS_PATH), count=len(bools))
        else:
            log.warning("flags_yaml_missing", path=str(_FLAGS_PATH))
            _loaded = {"flags": {}, "strings": {}}
    return _loaded


def _env_override(name: str) -> bool | None:
    """Return True/False if FLAG_<NAME> is set, else None."""
    raw = os.getenv(f"FLAG_{name.upper()}")
    if raw is None:
        return None
    return raw.lower() in ("1", "true", "yes")


def get_flag(name: str, default: bool = False) -> bool:
    """Return a boolean feature flag.

    Precedence: env var FLAG_<NAME> > flags.yaml > settings.py default > default arg.
    """
    override = _env_override(name)
    if override is not None:
        return override

    data = _load()
    if name in data["flags"]:
        return bool(data["flags"][name])

    # Fall back to settings.py so existing ENABLE_* env vars keep working
    try:
        from analyzer.config import settings

        setting_val = getattr(settings, name, None)
        if isinstance(setting_val, bool):
            return setting_val
    except Exception:
        pass

    return default


def get_string_flag(name: str, default: str = "") -> str:
    """Return a string feature flag."""
    env_key = f"FLAG_{name.upper()}"
    raw = os.getenv(env_key)
    if raw is not None:
        return raw

    data = _load()
    return str(data["strings"].get(name, default))
