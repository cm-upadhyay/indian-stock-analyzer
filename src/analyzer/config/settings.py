"""Centralized application settings — single source of truth for all tunable constants.

Priority order (highest → lowest):
  1. Environment variable  (runtime override — Lambda env vars, local .env)
  2. config/settings.yaml  (committed defaults — change via PR, visible in git diff)
  3. Python field default  (last-resort fallback if YAML is absent)

Secrets (API keys, tokens) go in .env or SSM — never in settings.yaml or here.
Feature toggles (enable_hitl, enable_reflection, etc.) are now in config/flags.yaml
(Phase 3C OpenFeature). The fields below remain as fallback defaults only.

Override examples:
    LLM_PRIMARY_MODEL=gpt-5-mini             # switch model without redeploy
    REFLECTION_CONFIDENCE_THRESHOLD=0.70     # tighten reflection trigger
    NEWS_MAX_AGE_DAYS=14                     # drop articles older than 2 weeks
    ENABLE_HITL=true                         # enable human review gate
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

_YAML_PATH = Path(__file__).parents[3] / "config" / "settings.yaml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings, dotenv_settings]
        if _YAML_PATH.exists():
            sources.append(YamlConfigSettingsSource(settings_cls, yaml_file=_YAML_PATH))
        sources.append(file_secret_settings)
        return tuple(sources)

    # ── LLM models ────────────────────────────────────────────────────────────
    llm_primary_model: str = "gpt-5.4-mini"
    llm_smart_model: str = "gpt-5"
    llm_fallback_model: str = "gemini/gemini-1.5-flash"
    llm_temperature: float = Field(0.3, ge=0.0, le=2.0)
    # mem0ai v2.0.1 hardcodes max_tokens internally — only models that still accept
    # max_tokens work. gpt-5.4-mini requires max_completion_tokens (Mem0 bug).
    # Override via MEM0_LLM_MODEL env var once Mem0 fixes the issue.
    mem0_llm_model: str = "gpt-4o-mini"

    # ── Observability ─────────────────────────────────────────────────────────
    sentry_dsn: str = ""  # empty → Sentry disabled
    langfuse_public_key: str = ""  # empty → Langfuse disabled (falls back to local YAML)
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    otel_exporter_otlp_endpoint: str = ""  # empty → OTel spans exported to console only

    # ── Feature toggles (Phase 3C: use config/flags.yaml via OpenFeature) ───────
    # These remain as fallback defaults when flags.yaml is absent (e.g. Lambda without
    # the config/ COPY, or local dev without flags.yaml). get_flag() reads flags.yaml
    # first, then falls back to these settings, then the default= argument.
    enable_reflection: bool = True
    enable_hitl: bool = False
    enable_agentic_mode: bool = True
    memory_enabled: bool = True
    input_guard_enabled: bool = True
    guardrails_enabled: bool = True
    nemo_rails_enabled: bool = True
    enable_semantic_cache: bool = True  # Task 3.17 — semantic LLM cache

    # ── Phase 3C — Auth (Task 3.21) ───────────────────────────────────────────
    nextauth_secret: str = ""  # shared secret between Auth.js and FastAPI JWT verification

    # ── Reflection (moved to config/settings.yaml) ────────────────────────────
    reflection_confidence_threshold: float = Field(0.65, ge=0.0, le=1.0)
    reviewer_model: str = ""

    # ── Guardrails (moved to config/settings.yaml) ────────────────────────────
    max_guard_retries: int = Field(2, ge=0)
    guardrail_entry_deviation_pct: float = Field(0.05, ge=0.0, le=1.0)
    guardrail_stop_loss_min_pct: float = Field(0.02, ge=0.0, le=1.0)
    guardrail_stop_loss_max_pct: float = Field(0.08, ge=0.0, le=1.0)
    guardrail_min_confidence: float = Field(0.60, ge=0.0, le=1.0)

    # ── HITL (moved to config/settings.yaml) ──────────────────────────────────
    hitl_confidence_trigger: float = Field(0.50, ge=0.0, le=1.0)
    hitl_large_target_upside: float = Field(0.30, ge=0.0)
    hitl_timeout_secs: int = Field(1800, gt=0)
    hitl_db_path: str = "/tmp/data/hitl.db"
    admin_chat_id: str = ""
    telegram_bot_token: str = ""
    api_base_url: str = "http://localhost:8000"

    # ── Agentic loop (moved to config/settings.yaml) ──────────────────────────
    max_tool_calls: int = Field(5, ge=1)

    # ── News (moved to config/settings.yaml) ──────────────────────────────────
    news_max_age_days: int = Field(30, gt=0)
    news_fresh_days: int = Field(2, ge=0)

    # ── Token budget (moved to config/settings.yaml) ──────────────────────────
    daily_token_limit: int = Field(2_500_000, gt=0)


settings = Settings()  # type: ignore[call-arg]
