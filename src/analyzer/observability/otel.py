"""OpenTelemetry setup — vendor-neutral request + LLM call tracing.

Why OTel in addition to LangSmith and Langfuse?
    LangSmith and Langfuse are LLM-specific. OTel traces the full request lifecycle:
    FastAPI request → LangGraph node → LiteLLM call → S3 write → response.
    OTel uses the GenAI semantic conventions (2026-stable) for LLM spans so the data
    is portable — backend can swap from Jaeger to Grafana Tempo to AWS X-Ray by
    changing one env var, with no code changes.

GenAI semantic conventions used:
    gen_ai.system            — "openai" | "google_ai" | "anthropic"
    gen_ai.request.model     — "gpt-5.4-mini"
    gen_ai.usage.input_tokens
    gen_ai.usage.output_tokens
    gen_ai.response.finish_reasons

Graceful degradation:
    If OTEL_EXPORTER_OTLP_ENDPOINT is absent, no spans are emitted. The TracerProvider
    falls back to OTel's built-in NoOpTracerProvider — get_tracer() always returns a
    valid tracer object, so call sites don't need null checks.

Env:
    OTEL_EXPORTER_OTLP_ENDPOINT — OTLP/HTTP collector URL, e.g. http://localhost:4318
                                   or a cloud provider endpoint
    OTEL_SERVICE_NAME            — overrides the default service name (optional)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from fastapi import FastAPI

log = structlog.get_logger()

_initialised = False


def init_otel(service_name: str = "indian-stock-analyzer") -> None:
    """Initialize OTel trace provider. Idempotent — safe to call multiple times."""
    global _initialised
    if _initialised:
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint:
        log.debug("otel_disabled", hint="Set OTEL_EXPORTER_OTLP_ENDPOINT to enable tracing")
        return

    svc = os.getenv("OTEL_SERVICE_NAME", service_name)
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({SERVICE_NAME: svc})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces"))
        )
        trace.set_tracer_provider(provider)
        _initialised = True
        log.info("otel_initialized", endpoint=endpoint, service=svc)
    except ImportError:
        log.warning(
            "otel_not_installed",
            hint="pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http",
        )
    except Exception as e:
        log.warning("otel_init_failed", error=str(e))


def instrument_fastapi(app: FastAPI) -> None:
    """Wire OTel auto-instrumentation into a FastAPI app.

    Must be called after the FastAPI app is created and after init_otel().
    Creates a span for every request, including path, status code, and duration.
    """
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        log.info("otel_fastapi_instrumented")
    except ImportError:
        log.debug(
            "otel_fastapi_instrumentor_missing",
            hint="pip install opentelemetry-instrumentation-fastapi",
        )
    except Exception as e:
        log.warning("otel_fastapi_instrument_failed", error=str(e))


def get_tracer(name: str = "indian-stock-analyzer") -> Any:
    """Return an OTel tracer. Always returns a valid tracer — no-op if OTel not configured."""
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except ImportError:
        return _NoOpTracer()


def create_llm_span(
    tracer: Any,
    operation: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """Record a completed LLM generation as an OTel span with GenAI attributes."""
    try:
        with tracer.start_as_current_span(f"gen_ai.{operation}") as span:
            span.set_attribute("gen_ai.system", "openai")
            span.set_attribute("gen_ai.request.model", model)
            span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
    except Exception:
        pass


class _NoOpTracer:
    """Fallback tracer when OTel is not installed — call sites need no null checks."""

    def start_as_current_span(self, name: str, **kwargs: Any) -> Any:
        from contextlib import contextmanager

        @contextmanager
        def _noop() -> Any:
            yield _NoOpSpan()

        return _noop()


class _NoOpSpan:
    def set_attribute(self, *args: object, **kwargs: object) -> None:
        pass
