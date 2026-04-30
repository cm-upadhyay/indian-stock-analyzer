"""Centralized application settings — single source of truth for all tunable constants.

Every value can be overridden via environment variable (field name in SCREAMING_SNAKE_CASE).
Set values in .env for local dev, or AWS SSM Parameter Store for Lambda.

Secrets (API keys, tokens) go in .env or SSM — never commit them to git.

Override examples:
    LLM_PRIMARY_MODEL=gpt-5-mini             # switch primary model
    REFLECTION_CONFIDENCE_THRESHOLD=0.70     # tighten reflection trigger
    NEWS_MAX_AGE_DAYS=14                     # drop articles older than 2 weeks
    ENABLE_HITL=true                         # enable human review gate
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # unknown env vars are silently ignored — Lambda has many
        case_sensitive=False,
    )

    # ── LLM models ────────────────────────────────────────────────────────────
    # OpenAI free tier (data-sharing opt-in):
    #   PRIMARY bucket — 2.5M tokens/day: gpt-5.4-mini, gpt-5-mini, gpt-4o-mini
    #   SMART bucket   — 250K tokens/day: gpt-5, gpt-4o, o3
    llm_primary_model: str = "gpt-5.4-mini"
    llm_smart_model: str = "gpt-5"
    llm_fallback_model: str = "gemini/gemini-1.5-flash"
    llm_temperature: float = Field(0.3, ge=0.0, le=2.0)
    # mem0ai v2.0.1 hardcodes max_tokens internally — only models that still accept max_tokens work.
    # gpt-5.4-mini requires max_completion_tokens (Mem0 bug). Override via MEM0_LLM_MODEL env var
    # once Mem0 fixes the issue and you can use llm_primary_model here instead.
    mem0_llm_model: str = "gpt-4o-mini"

    # ── Token budget ──────────────────────────────────────────────────────────
    daily_token_limit: int = Field(2_500_000, gt=0)

    # ── Reflection ────────────────────────────────────────────────────────────
    # Smarter model reviews BUY/SELL verdicts below this confidence threshold.
    enable_reflection: bool = True
    reflection_confidence_threshold: float = Field(0.65, ge=0.0, le=1.0)
    reviewer_model: str = ""  # empty → falls back to llm_smart_model at runtime

    # ── Guardrails ────────────────────────────────────────────────────────────
    # Business-rule validators on LLM verdict fields.
    guardrails_enabled: bool = True
    max_guard_retries: int = Field(2, ge=0)
    guardrail_entry_deviation_pct: float = Field(0.05, ge=0.0, le=1.0)
    guardrail_stop_loss_min_pct: float = Field(0.02, ge=0.0, le=1.0)
    guardrail_stop_loss_max_pct: float = Field(0.08, ge=0.0, le=1.0)
    guardrail_min_confidence: float = Field(0.60, ge=0.0, le=1.0)

    # ── HITL ──────────────────────────────────────────────────────────────────
    # Human-in-the-loop approval gate for high-stakes verdicts.
    enable_hitl: bool = False
    hitl_confidence_trigger: float = Field(0.50, ge=0.0, le=1.0)
    hitl_large_target_upside: float = Field(0.30, ge=0.0)
    hitl_timeout_secs: int = Field(1800, gt=0)
    hitl_db_path: str = "data/hitl.db"
    admin_chat_id: str = ""
    telegram_bot_token: str = ""
    api_base_url: str = "http://localhost:8000"

    # ── Agentic loop ──────────────────────────────────────────────────────────
    # LLM-driven tool-calling loop (Phase 3A). Safety cap on tool calls per stock.
    enable_agentic_mode: bool = True
    max_tool_calls: int = Field(5, ge=1)

    # ── News ──────────────────────────────────────────────────────────────────
    # Articles older than news_max_age_days are dropped before reaching the LLM.
    # Articles within news_fresh_days get no age label prepended to their title.
    news_max_age_days: int = Field(30, gt=0)
    news_fresh_days: int = Field(2, ge=0)


settings = Settings()  # type: ignore[call-arg]
