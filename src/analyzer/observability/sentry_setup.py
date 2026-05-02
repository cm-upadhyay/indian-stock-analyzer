"""Sentry error aggregation — backend (Lambda/ECS) + browser (Next.js via Phase 3B).

What Sentry adds vs structlog:
    structlog writes structured JSON to CloudWatch — searchable but no grouping,
    no release correlation, no stack-trace deduplication.
    Sentry groups identical errors, links spikes to the deploying commit (via release tag),
    and provides breadcrumbs (recent log events before the crash).

Release tagging:
    The release tag is the git SHA injected at build time as GIT_SHA env var.
    Error spikes in Sentry can be correlated to the exact commit that introduced them.
    Set GIT_SHA in the ECS task definition / Lambda env or CI deploy step.

Graceful degradation:
    If SENTRY_DSN is absent, sentry_sdk is never imported. The pipeline runs without
    error tracking — no exception, no performance impact.

Env:
    SENTRY_DSN      — from Sentry project settings (https://sentry.io/)
    GIT_SHA         — git commit SHA injected by CI deploy (optional — defaults to "unknown")
    ENVIRONMENT     — "production" | "staging" | "development" (default: "development")
"""

from __future__ import annotations

import os
from typing import Any

import structlog

log = structlog.get_logger()

_initialised = False


def init_sentry() -> None:
    """Initialize Sentry SDK. Idempotent — safe to call multiple times."""
    global _initialised
    if _initialised:
        return

    dsn = os.getenv("SENTRY_DSN", "")
    if not dsn:
        log.debug("sentry_disabled", hint="Set SENTRY_DSN to enable error tracking")
        return

    env = os.getenv("ENVIRONMENT", "development")
    release = os.getenv("GIT_SHA", "unknown")

    try:
        import sentry_sdk

        integrations: list[Any] = []
        try:
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.starlette import StarletteIntegration

            integrations = [StarletteIntegration(transaction_style="url"), FastApiIntegration()]
        except ImportError:
            pass  # FastAPI integrations optional — backend Lambda doesn't need them

        sentry_sdk.init(
            dsn=dsn,
            release=release,
            environment=env,
            traces_sample_rate=0.1,  # 10% of requests get performance traces
            profiles_sample_rate=0.0,  # profiling off (cost)
            integrations=integrations,
            before_send=_scrub_pii,  # type: ignore[arg-type]
        )
        _initialised = True
        log.info("sentry_initialized", environment=env, release=release)
    except ImportError:
        log.warning("sentry_not_installed", hint="pip install sentry-sdk")
    except Exception as e:
        log.warning("sentry_init_failed", error=str(e))


def _scrub_pii(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    """Strip known PII fields before Sentry receives the event.

    Sentry sees exception traces which may contain API keys or user data in
    local variables. We remove known sensitive keys to reduce PII surface.
    """
    for frame in (
        event.get("exception", {}).get("values", [{}])[0].get("stacktrace", {}).get("frames", [])
    ):
        for var in list(frame.get("vars", {}).keys()):
            if any(k in var.lower() for k in ("key", "token", "password", "secret", "api")):
                frame["vars"][var] = "[REDACTED]"
    return event


def capture_exception(exc: BaseException) -> None:
    """Explicitly capture an exception to Sentry (for caught errors we still want to track)."""
    if not _initialised:
        return
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception:
        pass


def flush() -> None:
    """Flush pending Sentry events. Call before Lambda/ECS task returns."""
    if not _initialised:
        return
    try:
        import sentry_sdk

        sentry_sdk.flush(timeout=2)
    except Exception:
        pass
