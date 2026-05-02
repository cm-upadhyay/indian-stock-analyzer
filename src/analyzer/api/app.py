"""FastAPI app — REST API for the Indian Stock Analyzer.

Endpoints:
    GET  /health                 — liveness / dependency check
    GET  /latest                 — all verdicts for a given date (default: today)
    GET  /stock/{symbol}         — verdict for one symbol on a given date
    GET  /morning                — morning follow-up notes for a given date
    GET  /accuracy               — rolling 30-day accuracy stats
    GET  /stream/{symbol}        — SSE stream (active subscribers only — Task 3.21)
    POST /hitl/approve/{id}      — admin approve a HITL-paused verdict
    POST /hitl/reject/{id}       — admin reject a HITL-paused verdict
    POST /webhooks/razorpay      — Razorpay subscription lifecycle events (Task 3.21)

Auth:
    Bearer JWT   — Auth.js HS256 token on all user-facing endpoints (Task 3.21).
                   Open access when NEXTAUTH_SECRET is not configured (local dev).
    X-API-Key    — Server-to-server / HITL Telegram button endpoints only.

Mangum wraps this for Lambda. Same code runs locally with uvicorn.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncGenerator
from datetime import UTC, date
from typing import Any

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security.api_key import APIKeyHeader
from mangum import Mangum
from pydantic import BaseModel

from analyzer.utils.logging import configure_logging
from analyzer.utils.storage import AnalysisStore, MorningNoteStore

load_dotenv()  # no-op on Lambda (vars come from env); loads .env in local dev
configure_logging()
log = structlog.get_logger()

from analyzer.observability.otel import init_otel, instrument_fastapi  # noqa: E402
from analyzer.observability.sentry_setup import init_sentry  # noqa: E402
from analyzer.utils.secrets import load_secrets_from_ssm  # noqa: E402

load_secrets_from_ssm()
init_sentry()
init_otel()

app = FastAPI(title="Indian Stock Analyzer API", version="3.0.0")

instrument_fastapi(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*"
    ],  # tightened in Phase 4 once Vercel domains are known  # nosemgrep: python.fastapi.security.wildcard-cors.wildcard-cors
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


def _require_user_jwt(authorization: str | None = Header(None)) -> dict[str, Any]:
    """Verify an Auth.js HS256 JWT for user-facing endpoints (Task 3.21).

    Auth.js (NextAuth v5) signs JWTs with NEXTAUTH_SECRET. The Next.js proxy reads
    the session cookie and forwards the raw token as Authorization: Bearer <token>.

    On success the decoded payload is returned (contains sub, email, name at minimum).
    Raises 401 when NEXTAUTH_SECRET is set but the token is missing or invalid.
    Returns {} (open access) when NEXTAUTH_SECRET is not configured — local dev only.
    """
    secret = os.getenv("NEXTAUTH_SECRET", "")
    if not secret:
        return {}  # open access — local dev without auth configured

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        from jose import jwt

        payload: dict[str, Any] = jwt.decode(token, secret, algorithms=["HS256"])

        # Lazy-upsert the user so DynamoDB is always in sync after login.
        user_id = payload.get("sub", "")
        email = payload.get("email", "")
        name = payload.get("name", "")
        if user_id and email:
            try:
                from analyzer.users.store import upsert_user

                upsert_user(user_id, email, name)
            except Exception:
                pass  # never fail a user request because DynamoDB is unavailable

        return payload
    except Exception as exc:
        log.warning("jwt_verification_failed", error=str(exc))
        raise HTTPException(status_code=401, detail="Invalid token") from exc


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
    _user: dict[str, Any] = Security(_require_user_jwt),  # noqa: B008
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
    _user: dict[str, Any] = Security(_require_user_jwt),  # noqa: B008
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
    _user: dict[str, Any] = Security(_require_user_jwt),  # noqa: B008
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
def accuracy(_user: dict[str, Any] = Security(_require_user_jwt)) -> AccuracyResponse:  # noqa: B008
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


@app.get("/stream/{symbol}")
async def stream_analysis(
    symbol: str,
    user: dict[str, Any] = Security(_require_user_jwt),  # noqa: B008
) -> StreamingResponse:
    """SSE stream of live analysis events — active subscribers only (Task 3.21).

    Requires an active Razorpay subscription. Free-tier users get a 402 with an
    upgrade prompt. Open access when NEXTAUTH_SECRET is not configured (local dev).

    Format: standard SSE — each event is 'data: <json>\\n\\n'.
    """
    # Subscription gate — skip when NEXTAUTH_SECRET not configured (local dev)
    if user and os.getenv("NEXTAUTH_SECRET"):
        user_id = user.get("sub", "")
        if user_id:
            try:
                from analyzer.users.store import get_user

                record = get_user(user_id)
                status = (record or {}).get("subscription_status", "free")
                if status != "active":
                    raise HTTPException(
                        status_code=402,
                        detail="Active subscription required for live SSE streaming",
                    )
            except HTTPException:
                raise
            except Exception:
                pass  # DynamoDB unavailable — degrade gracefully, allow stream
    import hashlib

    # Check for a pending progress file written by the pipeline
    progress_path = (
        __import__("pathlib").Path("/tmp/data/stream")
        / hashlib.sha256(symbol.encode()).hexdigest()[:8]
        / "events.jsonl"
    )

    async def generate() -> AsyncGenerator[str, None]:
        yield f"data: {json.dumps({'event': 'connected', 'symbol': symbol})}\n\n"

        if not progress_path.exists():
            # No live run in progress — emit the current stored verdict if available
            today = date.today()
            verdict = _store.load(today, symbol)
            if verdict:
                yield f"data: {json.dumps({'event': 'verdict_ready', 'symbol': symbol, 'date': str(today)})}\n\n"
            yield f"data: {json.dumps({'event': 'done', 'symbol': symbol})}\n\n"
            return

        # Stream events from the live run
        offset = 0
        idle_ticks = 0
        max_idle_secs = 300  # 5-min timeout
        while idle_ticks < max_idle_secs:
            try:
                lines = progress_path.read_text().splitlines()
            except Exception:
                break
            if len(lines) > offset:
                for line in lines[offset:]:
                    yield f"data: {line}\n\n"
                    if json.loads(line).get("event") == "done":
                        return
                offset = len(lines)
                idle_ticks = 0
            else:
                idle_ticks += 1
            await asyncio.sleep(1)

        yield f"data: {json.dumps({'event': 'timeout', 'symbol': symbol})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/webhooks/razorpay", include_in_schema=False)
async def razorpay_webhook(request: Request) -> dict[str, str]:
    """Razorpay subscription lifecycle webhook (Task 3.21).

    Verified with HMAC-SHA256(raw_body, RAZORPAY_WEBHOOK_SECRET).
    Reacts to: subscription.activated → active, subscription.halted → lapsed,
    subscription.cancelled / subscription.completed → cancelled (stores expires_at).

    The Razorpay subscription must be created with notes.user_id = <Google sub>.
    """
    import hashlib
    import hmac

    body = await request.body()
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    if webhook_secret:
        sig = request.headers.get("X-Razorpay-Signature", "")
        expected = hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            log.warning("razorpay_webhook_invalid_signature")
            raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    event: str = payload.get("event", "")
    entity: dict = (  # type: ignore[type-arg]
        payload.get("payload", {}).get("subscription", {}).get("entity", {})
    )
    user_id: str = entity.get("notes", {}).get("user_id", "")
    sub_id: str = entity.get("id", "")

    if not user_id:
        log.warning("razorpay_webhook_missing_user_id", event=event, sub_id=sub_id)
        return {"status": "ignored", "reason": "no user_id in subscription notes"}

    from analyzer.users.store import update_subscription

    if event == "subscription.activated":
        update_subscription(user_id, "active", sub_id)
    elif event == "subscription.halted":
        update_subscription(user_id, "lapsed", sub_id)
    elif event in ("subscription.cancelled", "subscription.completed"):
        current_end: int = entity.get("current_end", 0)
        expires_at = ""
        if current_end:
            from datetime import datetime

            expires_at = datetime.fromtimestamp(current_end, tz=UTC).isoformat()
        update_subscription(user_id, "cancelled", sub_id, expires_at)
    else:
        log.info("razorpay_webhook_unhandled_event", event=event)

    log.info("razorpay_webhook_processed", event=event, user_id=user_id)
    return {"status": "ok", "event": event}


@app.post("/hitl/approve/{thread_id}")
def hitl_approve(thread_id: str, _: None = Security(_require_api_key)) -> dict[str, str]:  # noqa: B008
    """Record an admin approval for a HITL-paused verdict. Called by the Telegram button URL."""
    from analyzer.hitl.approver import record_decision

    record_decision(thread_id, approved=True)
    log.info("hitl_approve_endpoint", thread_id=thread_id)
    return {"status": "approved", "thread_id": thread_id}


@app.post("/hitl/reject/{thread_id}")
def hitl_reject(thread_id: str, _: None = Security(_require_api_key)) -> dict[str, str]:  # noqa: B008
    """Record an admin rejection for a HITL-paused verdict. Called by the Telegram button URL."""
    from analyzer.hitl.approver import record_decision

    record_decision(thread_id, approved=False)
    log.info("hitl_reject_endpoint", thread_id=thread_id)
    return {"status": "rejected", "thread_id": thread_id}


# Lambda handler
handler = Mangum(app)
