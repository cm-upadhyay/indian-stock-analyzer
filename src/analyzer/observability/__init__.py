"""Observability layer — Langfuse prompt registry, Sentry error tracking, OTel spans.

All three are optional enhancements with graceful degradation:
    - Langfuse: prompt registry + LLM call tracing (LANGFUSE_PUBLIC_KEY required)
    - Sentry: error aggregation + session replay (SENTRY_DSN required)
    - OTel: vendor-neutral request/LLM spans (OTEL_EXPORTER_OTLP_ENDPOINT required)

Import from sub-modules directly:
    from analyzer.observability.sentry_setup import init_sentry
    from analyzer.observability.otel import init_otel
    from analyzer.observability.langfuse_client import get_prompt, flush
"""
