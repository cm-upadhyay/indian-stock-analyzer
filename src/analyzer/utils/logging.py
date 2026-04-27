"""Logging configuration — call configure_logging() once at process startup.

Local dev  → colored, human-readable key=value lines (easy to read in terminal)
Lambda/CI  → JSON one-liner per event (CloudWatch can filter by field)

The switch is driven by the LOG_FORMAT env var:
  LOG_FORMAT=json   → JSON (set this in Lambda environment variables)
  LOG_FORMAT=pretty → colored dev output (default)
"""

from __future__ import annotations

import logging
import os
import sys

import structlog


def configure_logging() -> None:
    """Wire up structlog. Call this once at the top of __main__.py and each Lambda handler."""
    log_format = os.getenv("LOG_FORMAT", "pretty")
    level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_str, logging.INFO)

    # stdlib root logger — format="%(message)s" so structlog owns all formatting
    logging.basicConfig(stream=sys.stdout, level=level, format="%(message)s")

    # Shared processors that run for every log event regardless of format
    shared_processors: list[structlog.types.Processor] = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),  # adds "timestamp" field
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if log_format == "json":
        # Lambda / CI — one JSON object per line, CloudWatch can query by any field
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Local dev — colored, aligned key=value output
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
