"""FastAPI app — REST API for the Indian Stock Analyzer.

Versioned endpoints (all user-facing):
    GET  /api/v1/health          — liveness / dependency check
    GET  /api/v1/latest          — all verdicts for a given date (default: today)
    GET  /api/v1/stock/{symbol}  — verdict for one symbol on a given date
    GET  /api/v1/morning         — morning follow-up notes for a given date
    GET  /api/v1/accuracy        — rolling 30-day accuracy stats
    GET  /api/v1/me              — current user profile + subscription status
    GET  /api/v1/stream/{symbol} — SSE stream (active subscribers only)

Admin:
    GET  /api/v1/admin/subscribers       — subscriber delivery health
    POST /api/v1/admin/subscribers/seed  — one-time seed from TELEGRAM_CHAT_IDS env var

Unversioned (external callbacks — URLs already registered elsewhere):
    POST /api/v1/telegram/webhook — Telegram bot update receiver (subscribe/verify/unsubscribe)
    POST /webhooks/razorpay       — Razorpay subscription lifecycle events
    POST /hitl/approve/{id}       — admin approve a HITL-paused verdict
    POST /hitl/reject/{id}        — admin reject a HITL-paused verdict

Auth:
    Bearer JWT   — Auth.js HS256 token on all user-facing endpoints.
                   Open access when NEXTAUTH_SECRET is not configured (local dev).
    X-API-Key    — Server-to-server / HITL Telegram button endpoints only.

Mangum wraps this for Lambda. Same code runs locally with uvicorn.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import time
from collections.abc import AsyncGenerator
from datetime import UTC, date
from typing import Any

import structlog
from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, FastAPI, Header, HTTPException, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security.api_key import APIKeyHeader
from mangum import Mangum
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

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

app = FastAPI(title="Indian Stock Analyzer API", version="4.0.0")

instrument_fastapi(app)


# Rate limiter — in-memory per container.
# Note: Lambda containers are ephemeral so limits reset on cold-start.
# Cross-container abuse protection is handled by WAF (2000 req/IP/5 min).
def _get_real_ip(request: Request) -> str:
    """Real client IP — CloudFront sets X-Forwarded-For with client IP first."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_get_real_ip)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# CORS — restrict to known frontend origins in prod; wildcard in dev.
_allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# v1 router — all user-facing endpoints live here
v1 = APIRouter(prefix="/api/v1")

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


class MeResponse(BaseModel):
    user_id: str
    email: str
    name: str
    subscription_status: str  # free | active | lapsed | cancelled
    telegram_linked: bool
    chat_username: str
    email_opt_out: bool = False


class LinkCodeResponse(BaseModel):
    code: str
    expires_in_seconds: int


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


@v1.api_route("/health", methods=["GET", "HEAD"], response_model=HealthResponse)
@limiter.limit("120/minute")
def health(request: Request) -> HealthResponse:
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


def _load_analyses(run_date: str | None) -> tuple[date, list[VerdictOut]]:
    target = _parse_date(run_date)
    pairs = _store.load_all(target)
    if not pairs and run_date is None:
        most_recent = _store.latest_date()
        if most_recent and most_recent != target:
            target = most_recent
            pairs = _store.load_all(target)
    return target, [_to_verdict_out(sym, v) for sym, v in pairs]


@v1.get("/latest", response_model=LatestResponse)
@limiter.limit("120/hour")
def latest(
    request: Request,
    run_date: str | None = None,
) -> LatestResponse:
    """Free-tier: top 10 picks, no auth required, CDN-cacheable."""
    target, analyses = _load_analyses(run_date)
    sliced = analyses[:10]
    return LatestResponse(date=str(target), count=len(sliced), analyses=sliced)


@v1.get("/pro/latest", response_model=LatestResponse)
@limiter.limit("60/hour")
def pro_latest(
    request: Request,
    run_date: str | None = None,
    user: dict[str, Any] = Security(_require_user_jwt),  # noqa: B008
) -> LatestResponse:
    """Pro-tier: all picks, requires active subscription, bypasses CDN cache."""
    if os.getenv("NEXTAUTH_SECRET"):
        user_id = user.get("sub", "")
        if user_id:
            try:
                from analyzer.users.store import get_user

                record = get_user(user_id) or {}
                if record.get("subscription_status", "free") != "active":
                    raise HTTPException(
                        status_code=402,
                        detail="Active subscription required",
                    )
            except HTTPException:
                raise
            except Exception:
                pass  # degrade gracefully if DynamoDB unavailable

    target, analyses = _load_analyses(run_date)
    return LatestResponse(date=str(target), count=len(analyses), analyses=analyses)


@v1.get("/stock/{symbol}", response_model=StockResponse)
@limiter.limit("60/hour")
def get_stock(
    request: Request,
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


@v1.get("/morning", response_model=MorningResponse)
@limiter.limit("60/hour")
def morning(
    request: Request,
    run_date: str | None = None,
    user: dict[str, Any] = Security(_require_user_jwt),  # noqa: B008
) -> MorningResponse:
    """Morning follow-up notes — Pro subscribers only."""
    # Pro gate: reject free users when auth is configured
    if user and os.getenv("NEXTAUTH_SECRET"):
        user_id = user.get("sub", "")
        if user_id:
            try:
                from analyzer.users.store import get_user

                record = get_user(user_id) or {}
                if record.get("subscription_status", "free") != "active":
                    raise HTTPException(
                        status_code=402,
                        detail="Morning notes require a Pro subscription",
                    )
            except HTTPException:
                raise
            except Exception:
                pass  # degrade gracefully if DynamoDB unavailable

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


@v1.get("/accuracy", response_model=AccuracyResponse)
@limiter.limit("60/hour")
def accuracy(request: Request) -> AccuracyResponse:
    """Running accuracy stats for the last 30 days. Added in Phase 3A (Task 3.2).

    Public by design (PRD): the accuracy page is the trust surface anyone can
    inspect before signing up — rate-limited per IP instead of JWT-gated.
    """
    from analyzer.outcomes.tracker import get_accuracy_stats

    stats = get_accuracy_stats()

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


@v1.get("/me", response_model=MeResponse)
@limiter.limit("60/hour")
def me(request: Request, user: dict[str, Any] = Security(_require_user_jwt)) -> MeResponse:  # noqa: B008
    """Current user's profile, subscription status, and Telegram link state."""
    user_id = user.get("sub", "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token — no sub claim")

    from analyzer.users.store import get_user

    record = get_user(user_id) or {}
    return MeResponse(
        user_id=user_id,
        email=user.get("email", ""),
        name=user.get("name", ""),
        subscription_status=record.get("subscription_status", "free"),
        telegram_linked=bool(record.get("chat_id")),
        chat_username=record.get("chat_username", ""),
        email_opt_out=bool(record.get("email_opt_out", False)),
    )


@v1.post("/link-code", response_model=LinkCodeResponse)
@limiter.limit("10/minute")
def create_link_code(
    request: Request,
    user: dict[str, Any] = Security(_require_user_jwt),  # noqa: B008
) -> LinkCodeResponse:
    """Generate a 6-digit Telegram link code for the authenticated user (expires in 15 min)."""
    user_id = user.get("sub", "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token — no sub claim")

    from analyzer.users.linking import generate_link_code

    code = generate_link_code(user_id)
    return LinkCodeResponse(code=code, expires_in_seconds=900)


@v1.delete("/unlink-telegram")
@limiter.limit("10/minute")
def unlink_telegram_endpoint(
    request: Request,
    user: dict[str, Any] = Security(_require_user_jwt),  # noqa: B008
) -> dict[str, str]:
    """Remove the Telegram link from the authenticated user's account."""
    user_id = user.get("sub", "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token — no sub claim")

    from analyzer.users.store import unlink_telegram

    unlink_telegram(user_id)
    return {"status": "ok"}


@v1.get("/unsubscribe-email")
@limiter.limit("30/hour")
def unsubscribe_email(request: Request, token: str) -> dict[str, str]:
    """Token-based email unsubscribe — no login required.

    Token format: <user_id>.<hmac>. Validates HMAC with NEXTAUTH_SECRET.
    Idempotent — safe to call multiple times.
    """
    import base64
    import hashlib
    import hmac as hmac_lib

    secret = os.getenv("NEXTAUTH_SECRET", "").encode()
    if not secret:
        raise HTTPException(status_code=503, detail="Unsubscribe not configured")

    try:
        user_id, received_hmac = token.rsplit(".", 1)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid token format") from None

    expected = base64.urlsafe_b64encode(
        hmac_lib.new(secret, user_id.encode(), hashlib.sha256).digest()[:12]
    ).decode()

    if not hmac_lib.compare_digest(expected, received_hmac):
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    from analyzer.users.store import set_email_opt_out

    set_email_opt_out(user_id, opt_out=True)
    log.info("email_unsubscribed_via_token", user_id=user_id)
    return {"status": "unsubscribed"}


@v1.get("/stream/{symbol}")
@limiter.limit("20/hour")
async def stream_analysis(
    request: Request,
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
        log.warning("razorpay_webhook_missing_user_id", event_name=event, sub_id=sub_id)
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
        log.info("razorpay_webhook_unhandled_event", event_name=event)

    log.info("razorpay_webhook_processed", event_name=event, user_id=user_id)
    return {"status": "ok", "event": event}


@app.post("/hitl/approve/{thread_id}")
async def hitl_approve(thread_id: str, _: None = Security(_require_api_key)) -> dict[str, str]:  # noqa: B008
    """Resume a HITL-paused graph run with admin approval."""
    from analyzer.llm.formatter import format_telegram
    from analyzer.notify.telegram import send_message, send_verdict
    from analyzer.pipeline.graph_4pm import resume_4pm

    admin_chat = os.getenv("ADMIN_CHAT_ID", "")
    state = resume_4pm(thread_id, approved=True)

    if state is None:
        if admin_chat:
            await send_message("⏱ HITL verdict expired or not found.", chat_ids=[admin_chat])
        log.warning("hitl_approve_failed", thread_id=thread_id)
        return {"status": "expired_or_not_found", "thread_id": thread_id}

    if state.verdict and state.stock and state.scoring:
        await send_verdict(
            "✅ *Late addition — approved after review:*\n\n"
            + format_telegram(
                symbol=state.stock.symbol,
                company_name=state.stock.company_name,
                current_price=state.stock.current_price,
                verdict=state.verdict,
                scoring=state.scoring,
            )
        )

    if admin_chat:
        symbol = thread_id.split("_")[0]
        await send_message(f"✅ *{symbol}* verdict published.", chat_ids=[admin_chat])

    log.info("hitl_approved", thread_id=thread_id)
    return {"status": "approved", "thread_id": thread_id}


@app.post("/hitl/reject/{thread_id}")
async def hitl_reject(thread_id: str, _: None = Security(_require_api_key)) -> dict[str, str]:  # noqa: B008
    """Resume a HITL-paused graph run with admin rejection."""
    from analyzer.notify.telegram import send_message
    from analyzer.pipeline.graph_4pm import resume_4pm

    admin_chat = os.getenv("ADMIN_CHAT_ID", "")
    state = resume_4pm(thread_id, approved=False)

    if state is None:
        if admin_chat:
            await send_message("⏱ HITL verdict expired or not found.", chat_ids=[admin_chat])
        log.warning("hitl_reject_failed", thread_id=thread_id)
        return {"status": "expired_or_not_found", "thread_id": thread_id}

    if admin_chat:
        symbol = thread_id.split("_")[0]
        await send_message(f"❌ *{symbol}* verdict rejected — dropped.", chat_ids=[admin_chat])

    log.info("hitl_rejected", thread_id=thread_id)
    return {"status": "rejected", "thread_id": thread_id}


@app.post("/api/v1/telegram/webhook", include_in_schema=False)
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    """Receive Telegram bot updates (subscribe/verify/unsubscribe/HITL callbacks).

    Telegram posts updates here when users message the bot.
    Verified with X-Telegram-Bot-Api-Secret-Token header.

    Responds 200 immediately and processes in a background task so Telegram
    never sees a timeout — critical for HITL callback_query which triggers
    graph resume + Telegram sends that can take 10-30 seconds.
    """
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if secret:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(secret, token):
            log.warning("telegram_webhook_invalid_secret")
            raise HTTPException(status_code=403, detail="Invalid webhook token")

    try:
        update = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    from analyzer.notify.telegram import handle_update

    background_tasks.add_task(handle_update, update)
    return {"status": "ok"}


@app.get("/api/v1/admin/subscribers")
async def get_subscribers(
    _user: dict[str, Any] = Security(_require_user_jwt),  # noqa: B008
) -> dict[str, Any]:
    """Subscriber delivery health dashboard (admin only)."""
    from analyzer.notify.subscribers import get_all

    items = get_all()
    confirmed = [i for i in items if i.get("status") == "confirmed"]
    pending = [i for i in items if i.get("status") == "pending"]
    inactive = [i for i in items if i.get("status") == "inactive"]
    return {
        "total": len(items),
        "confirmed": len(confirmed),
        "pending": len(pending),
        "inactive": len(inactive),
        "subscribers": [
            {
                "chat_id": i["chat_id"],
                "username": i.get("username", ""),
                "status": i["status"],
                "confirmed_at": i.get("confirmed_at", ""),
                "consecutive_failures": int(i.get("consecutive_failures", 0)),
            }
            for i in items
        ],
    }


@app.post("/api/v1/admin/subscribers/seed")
async def seed_subscribers(
    _user: dict[str, Any] = Security(_require_user_jwt),  # noqa: B008
) -> dict[str, Any]:
    """One-time migration: seed confirmed subscribers from TELEGRAM_CHAT_IDS env var."""
    from analyzer.notify.subscribers import seed_from_env

    inserted = seed_from_env()
    return {"status": "ok", "inserted": inserted}


@app.post("/api/v1/admin/alert", include_in_schema=False)
async def sns_alert(request: Request) -> dict[str, str]:
    """Receive SNS CloudWatch alarm notifications and forward to admin Telegram.

    SNS sends a SubscriptionConfirmation first (Type=SubscriptionConfirmation) —
    we auto-confirm it. Then alarm payloads (Type=Notification) are forwarded.
    No auth needed: SNS verifies delivery via its own signature mechanism.
    We validate the Topic ARN to reject spoofed calls.
    """
    import json as _json

    body = await request.body()
    try:
        payload = _json.loads(body)
    except Exception:
        return {"status": "ignored"}

    msg_type = payload.get("Type", "")
    topic_arn = payload.get("TopicArn", "")

    # Only accept from our alerts topic
    if "analyzer-alerts-prod" not in topic_arn:
        log.warning("sns_alert_unknown_topic", topic_arn=topic_arn)
        return {"status": "ignored"}

    if msg_type == "SubscriptionConfirmation":
        # Auto-confirm SNS subscription
        import requests as _requests

        confirm_url = payload.get("SubscribeURL", "")
        if confirm_url:
            try:
                _requests.get(confirm_url, timeout=10)
                log.info("sns_subscription_confirmed", topic_arn=topic_arn)
            except Exception as e:
                log.error("sns_confirm_failed", error=str(e))
        return {"status": "confirmed"}

    if msg_type == "Notification":
        from analyzer.notify.telegram import send_message

        alarm_msg = payload.get("Message", "")
        try:
            alarm_data = _json.loads(alarm_msg)
            alarm_name = alarm_data.get("AlarmName", "Unknown")
            new_state = alarm_data.get("NewStateValue", "?")
            reason = alarm_data.get("NewStateReason", "")[:200]
            runbook = alarm_data.get("AlarmDescription", "")
            text = (
                f"🚨 *CloudWatch Alarm*\n\n"
                f"*{alarm_name}*\n"
                f"State: `{new_state}`\n"
                f"{reason}\n\n"
                f"{runbook}"
            )
        except Exception:
            text = f"🚨 CloudWatch alert:\n{alarm_msg[:400]}"

        await send_message(text)
        log.info("sns_alarm_forwarded", topic_arn=topic_arn)
        return {"status": "forwarded"}

    return {"status": "ignored"}


app.include_router(v1)

# Lambda handler
handler = Mangum(app)
