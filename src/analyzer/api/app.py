"""FastAPI app — REST API for the Indian Stock Analyzer.

Endpoints:
    GET /health           — liveness / dependency check
    GET /latest           — all verdicts for a given date (default: today)
    GET /stock/{symbol}   — verdict for one symbol on a given date

Mangum wraps this for Lambda. Same code runs locally with uvicorn.
"""

from __future__ import annotations

import os
import time
from datetime import date

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from mangum import Mangum
from pydantic import BaseModel

from analyzer.utils.logging import configure_logging
from analyzer.utils.storage import AnalysisStore

load_dotenv()  # no-op on Lambda (vars come from env); loads .env in local dev
configure_logging()
log = structlog.get_logger()

from analyzer.utils.secrets import load_secrets_from_ssm  # noqa: E402

load_secrets_from_ssm()

app = FastAPI(title="Indian Stock Analyzer API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tightened in Phase 4 once Vercel domains are known
    allow_methods=["GET"],
    allow_headers=["*"],
)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _require_api_key(key: str | None = Security(_api_key_header)) -> None:
    """Reject requests missing or with wrong API key. /health is exempt."""
    expected = os.getenv("API_KEY", "")
    if not expected:
        return  # no key configured — open access (local dev)
    if key != expected:
        log.warning("api_auth_failed", key_present=bool(key))
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@app.middleware("http")
async def log_requests(request: Request, call_next):  # type: ignore[no-untyped-def]
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - start) * 1000)
    log.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
    )
    return response


_store = AnalysisStore()


# ── Response models ───────────────────────────────────────────────────────────


class VerdictOut(BaseModel):
    """Public verdict shape — excludes internal token counts."""

    symbol: str
    signal: str
    confidence: float
    entry: int | None
    stop_loss: int | None
    target: int | None
    whats_happening: str
    why_it_matters: str
    watch_out_for: str
    trader_action: str
    investor_action: str


class LatestResponse(BaseModel):
    date: str
    count: int
    analyses: list[VerdictOut]


class StockResponse(BaseModel):
    date: str
    symbol: str
    found: bool
    verdict: VerdictOut | None


class HealthResponse(BaseModel):
    status: str
    checks: dict[str, str]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _parse_date(run_date: str | None) -> date:
    if run_date is None:
        return date.today()
    try:
        return date.fromisoformat(run_date)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date '{run_date}' — use YYYY-MM-DD",
        ) from e


def _to_verdict_out(symbol: str, verdict) -> VerdictOut:  # type: ignore[no-untyped-def]
    return VerdictOut(
        symbol=symbol,
        signal=verdict.signal,
        confidence=verdict.confidence,
        entry=verdict.entry,
        stop_loss=verdict.stop_loss,
        target=verdict.target,
        whats_happening=verdict.whats_happening,
        why_it_matters=verdict.why_it_matters,
        watch_out_for=verdict.watch_out_for,
        trader_action=verdict.trader_action,
        investor_action=verdict.investor_action,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    checks: dict[str, str] = {}

    checks["llm_key"] = (
        "ok" if os.getenv("OPENAI_API_KEY") or os.getenv("GEMINI_API_KEY") else "missing"
    )

    backend = os.getenv("STORAGE_BACKEND", "local")
    if backend == "s3":
        checks["storage"] = "ok" if os.getenv("S3_BUCKET_NAME") else "missing_bucket"
    else:
        checks["storage"] = "ok"

    checks["api_key"] = "configured" if os.getenv("API_KEY") else "open"

    failing = [k for k, v in checks.items() if v not in ("ok", "configured", "open")]
    overall = "degraded" if failing else "ok"
    return HealthResponse(status=overall, checks=checks)


@app.get("/latest", response_model=LatestResponse)
def latest(
    run_date: str | None = None,
    _: None = Security(_require_api_key),
) -> LatestResponse:
    """All verdicts for a given date. Defaults to today."""
    target = _parse_date(run_date)
    pairs = _store.load_all(target)
    return LatestResponse(
        date=str(target),
        count=len(pairs),
        analyses=[_to_verdict_out(sym, v) for sym, v in pairs],
    )


@app.get("/stock/{symbol}", response_model=StockResponse)
def get_stock(
    symbol: str,
    run_date: str | None = None,
    _: None = Security(_require_api_key),
) -> StockResponse:
    """Verdict for one symbol. Symbol should include exchange suffix (e.g. RELIANCE.NS)."""
    target = _parse_date(run_date)
    verdict = _store.load(target, symbol)
    return StockResponse(
        date=str(target),
        symbol=symbol,
        found=verdict is not None,
        verdict=_to_verdict_out(symbol, verdict) if verdict else None,
    )


# Lambda handler
handler = Mangum(app)
