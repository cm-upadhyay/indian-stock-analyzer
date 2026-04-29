"""Daily token budget guard — hard cap on LLM token spend per day.

Why this exists: at 30 stocks/day × ~3K tokens/stock = ~90K tokens/day normally.
But if the agentic loop (Task 3.5) calls extra tools and the LLM generates long reasoning,
tokens can spike. Without a cap, a single bad run could exhaust the free-tier daily limit
(2.5M tokens for gpt-5.4-mini bucket) or trigger unexpected costs.

How it works:
    - Each LLM call reports its token count to DailyBudget.consume()
    - consume() returns True = budget OK, False = over budget
    - If over budget, the pipeline switches remaining stocks to the Phase 2 fixed pipeline
      instead of the agentic loop (graceful degradation, not a crash)
    - Budget resets at midnight (a new JSON file is created per day)

Storage: local JSON at data/budget/{YYYY-MM-DD}.json
         (One file per day — old files can be deleted safely)

Env:
    DAILY_TOKEN_LIMIT  — default 2_500_000 (OpenAI free tier for gpt-5.4-mini bucket)
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import structlog

from analyzer.config import settings

log = structlog.get_logger()

_BUDGET_ROOT = Path("data/budget")


class DailyBudget:
    """Thread-safe enough for our single-process Lambda use case.

    On Lambda each invocation is a separate process so there's no race condition.
    On local dev with --workers>1, there could be a race; acceptable for Phase 3A.
    """

    def __init__(self, daily_limit: int | None = None) -> None:
        self.daily_limit = daily_limit or settings.daily_token_limit
        self._path = _BUDGET_ROOT / f"{date.today()}.json"

    # ── Public API ────────────────────────────────────────────────────────────

    def consume(self, tokens: int, label: str = "") -> bool:
        """Record token usage. Returns True if still within budget, False if over."""
        current = self._load()
        new_total = current + tokens
        self._save(new_total)
        ok = new_total <= self.daily_limit
        log.info(
            "budget_consume",
            tokens=tokens,
            total=new_total,
            limit=self.daily_limit,
            within_budget=ok,
            label=label,
        )
        return ok

    def remaining(self) -> int:
        """Tokens remaining for today."""
        return max(0, self.daily_limit - self._load())

    def usage(self) -> int:
        """Total tokens consumed today."""
        return self._load()

    def is_exhausted(self) -> bool:
        return self._load() >= self.daily_limit

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load(self) -> int:
        if not self._path.exists():
            return 0
        try:
            return int(json.loads(self._path.read_text()).get("tokens", 0))
        except Exception:
            return 0

    def _save(self, total: int) -> None:
        _BUDGET_ROOT.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"date": str(date.today()), "tokens": total}))


# Module-level singleton — shared across the pipeline for a single run
_budget = DailyBudget()


def get_budget() -> DailyBudget:
    """Return the module-level DailyBudget singleton."""
    return _budget
