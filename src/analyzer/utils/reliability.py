"""Retry and circuit-breaker wrappers for all external API calls.

Usage:
    from analyzer.utils.reliability import retry_api, yfinance_breaker

    @yfinance_breaker
    @retry_api
    def my_yfinance_call():
        ...
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pybreaker
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

# Transient errors worth retrying — network timeouts, HTTP failures, provider rate limits.
# ValueError / KeyError / AttributeError are programmer errors; retrying them wastes time.
_TRANSIENT_ERRORS = (
    requests.exceptions.RequestException,  # all requests network errors
    TimeoutError,
    ConnectionError,
    OSError,
)

# ── Retry decorator ───────────────────────────────────────────────────────────
# 3 attempts, exponential backoff: 1s, 2s, 4s (max 10s)
_retry_api = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(_TRANSIENT_ERRORS),
    reraise=True,
)


def retry_api[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    return _retry_api(func)


# ── Circuit breakers (one per external provider) ──────────────────────────────
# Trip after 5 consecutive failures; half-open after 60s
_yfinance_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)
_nse_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)
_openai_breaker = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=30)


def yfinance_breaker[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    return cast("Callable[P, R]", _yfinance_breaker(func))


def nse_breaker[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    return cast("Callable[P, R]", _nse_breaker(func))


def openai_breaker[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    return cast("Callable[P, R]", _openai_breaker(func))
