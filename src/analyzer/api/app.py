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
from analyzer.utils.storage import AnalysisStore, MorningNoteStore

load_dotenv()  # no-op on Lambda (vars come from env); loads .env in local dev
configure_logging()
log = structlog.get_logger()

from analyzer.utils.secrets import load_secrets_from_ssm  # noqa: E402

load_secrets_from_ssm()

app = FastAPI(title="Indian Stock Analyzer API", version="3.0.0")

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
_morning_store = MorningNoteStore()


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


class MorningNoteOut(BaseModel):
    symbol: str
    company_name: str
    previous_signal: str
    status: str  # INTACT | WEAKENED | STRENGTHENED
    morning_text: str


class MorningResponse(BaseModel):
    date: str
    count: int
    notes: list[MorningNoteOut]


class AccuracyBySignal(BaseModel):
    total: int
    correct: int
    accuracy_pct: float


class AccuracyResponse(BaseModel):
    period_days: int
    total: int
    correct: int
    accuracy_pct: float
    target_hit_pct: float
    stop_triggered_pct: float
    by_signal: dict[str, AccuracyBySignal]


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


@app.get("/morning", response_model=MorningResponse)
def morning(
    run_date: str | None = None,
    _: None = Security(_require_api_key),
) -> MorningResponse:
    """All morning notes for a given date. Added in Phase 3A (Task 3.18 prep)."""
    target = _parse_date(run_date)
    records = _morning_store.load_all(str(target))
    return MorningResponse(
        date=str(target),
        count=len(records),
        notes=[
            MorningNoteOut(
                symbol=r.symbol,
                company_name=r.company_name,
                previous_signal=r.previous_signal,
                status=r.status,
                morning_text=r.morning_text,
            )
            for r in records
        ],
    )


@app.get("/accuracy", response_model=AccuracyResponse)
def accuracy(_: None = Security(_require_api_key)) -> AccuracyResponse:
    """Running accuracy stats for the last 30 days. Added in Phase 3A (Task 3.2)."""
    from analyzer.outcomes.tracker import load_accuracy_stats

    stats = load_accuracy_stats()

    by_signal_raw = stats.get("by_signal", {})
    by_signal: dict[str, AccuracyBySignal] = {}
    for sig, data in by_signal_raw.items():
        if isinstance(data, dict):
            by_signal[sig] = AccuracyBySignal(
                total=int(data.get("total", 0)),
                correct=int(data.get("correct", 0)),
                accuracy_pct=float(data.get("accuracy_pct", 0.0)),
            )

    return AccuracyResponse(
        period_days=30,
        total=int(stats.get("total", 0)),
        correct=int(stats.get("correct", 0)),
        accuracy_pct=float(stats.get("accuracy_pct", 0.0)),
        target_hit_pct=float(stats.get("target_hit_pct", 0.0)),
        stop_triggered_pct=float(stats.get("stop_triggered_pct", 0.0)),
        by_signal=by_signal,
    )


@app.post("/hitl/approve/{thread_id}")
def hitl_approve(thread_id: str, _: None = Security(_require_api_key)) -> dict:  # type: ignore[type-arg]
    """Record an admin approval for a HITL-paused verdict. Called by the Telegram button URL."""
    from analyzer.hitl.approver import record_decision

    record_decision(thread_id, approved=True)
    log.info("hitl_approve_endpoint", thread_id=thread_id)
    return {"status": "approved", "thread_id": thread_id}


@app.post("/hitl/reject/{thread_id}")
def hitl_reject(thread_id: str, _: None = Security(_require_api_key)) -> dict:  # type: ignore[type-arg]
    """Record an admin rejection for a HITL-paused verdict. Called by the Telegram button URL."""
    from analyzer.hitl.approver import record_decision

    record_decision(thread_id, approved=False)
    log.info("hitl_reject_endpoint", thread_id=thread_id)
    return {"status": "rejected", "thread_id": thread_id}


# Lambda handler
handler = Mangum(app)
