"""Mem0 wrapper — manages the three-tier memory store for the stock analyzer.

What is Mem0?
    Mem0 is an open-source memory library (MIT license) that provides a simple API
    to add, search, and retrieve memories. Under the hood it uses:
      - An LLM to extract key facts from raw text before storing
      - A vector store (ChromaDB locally, Qdrant/Pinecone in prod) for semantic search
      - A SQLite history database to track what was stored when

Why three tiers instead of one flat store?
    - Episodic: per-stock history (scoped to symbol) — "what did we predict for RELIANCE?"
    - Semantic: cross-stock patterns (global scope) — "what patterns work in general?"
    - Procedural: global heuristics (global scope) — "what mistakes should we avoid?"
    Scoping episodic per-symbol keeps the retrieval relevant and avoids unrelated noise.

Graceful degradation:
    If Mem0/ChromaDB is not installed or fails to initialise, all methods return
    empty results. The pipeline continues without memory — it's an enhancement, not
    a dependency. You'll see a warning log when this happens.

Local storage:
    Vector DB:  data/memory/chroma/
    History DB: data/memory/history.db

Env:
    OPENAI_API_KEY   — used by Mem0 for embeddings (text-embedding-3-small)
    MEMORY_ENABLED   — set to "false" to disable (default: true)
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import structlog

from analyzer.adapters.openai import PRIMARY_MODEL
from analyzer.config import settings
from analyzer.data.models import MorningNote, StockVerdict
from analyzer.memory.context import MemoryContext

log = structlog.get_logger()

_MEMORY_ROOT = Path("data/memory")


def _mem0_enabled() -> bool:
    return os.getenv("MEMORY_ENABLED", "true").lower() != "false"


def _build_config() -> dict:  # type: ignore[type-arg]
    """Build Mem0 configuration for local ChromaDB storage."""
    return {
        "llm": {
            "provider": "openai",
            "config": {
                "model": settings.mem0_llm_model,
                "temperature": 0,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": "text-embedding-3-small",
            },
        },
        "vector_store": {
            "provider": "chroma",
            "config": {
                "collection_name": "indian_stock_analyzer",
                "path": str(_MEMORY_ROOT / "chroma"),
            },
        },
        "history_db_path": str(_MEMORY_ROOT / "history.db"),
    }


def _get_memory():  # type: ignore[no-untyped-def]
    """Lazy-load Mem0 Memory instance. Returns None if not available."""
    try:
        from mem0 import Memory

        _MEMORY_ROOT.mkdir(parents=True, exist_ok=True)
        return Memory.from_config(_build_config())
    except ImportError:
        log.warning("mem0_not_installed", hint="pip install mem0ai chromadb")
        return None
    except Exception as e:
        log.warning("mem0_init_failed", error=str(e))
        return None


class MemoryStore:
    """Three-tier memory store for the stock analyzer pipeline.

    Usage (from a LangGraph node):
        store = MemoryStore()
        context = store.get_context("RELIANCE.NS")
        # ... pass context to call_analyst() ...
        store.add_verdict("RELIANCE.NS", date.today(), verdict)
    """

    def __init__(self) -> None:
        self._mem = _get_memory() if _mem0_enabled() else None  # type: ignore[no-untyped-call]

    # ── Write ─────────────────────────────────────────────────────────────────

    def add_verdict(self, symbol: str, run_date: date, verdict: StockVerdict) -> None:
        """Store a new verdict as an episodic memory for this stock."""
        if self._mem is None:
            return
        entry = self._format_episodic(symbol, run_date, verdict)
        try:
            self._mem.add(
                entry, user_id=symbol, metadata={"date": str(run_date), "tier": "episodic"}
            )
            log.info("memory_added", symbol=symbol, date=str(run_date))
        except Exception as e:
            log.warning("memory_add_failed", symbol=symbol, error=str(e))

    def add_outcome_result(self, symbol: str, outcome) -> None:  # type: ignore[no-untyped-def]
        """Write the actual outcome of a past verdict back into episodic memory.

        Called in node_check_outcomes immediately after the OutcomeRecord is stored,
        so that node_inject_memory (which runs next) picks up the result and the LLM
        knows whether its last call on this stock was correct or wrong.
        """
        if self._mem is None:
            return
        result = (
            "CORRECT"
            if outcome.direction_correct
            else ("WRONG" if outcome.direction_correct is False else "NEUTRAL")
        )
        detail_parts = []
        if outcome.target_hit is not None:
            detail_parts.append(f"target_hit={outcome.target_hit}")
        if outcome.stop_triggered is not None:
            detail_parts.append(f"stop_triggered={outcome.stop_triggered}")
        detail = ", ".join(detail_parts) or "direction-neutral"
        entry = (
            f"{outcome.verdict_date}: {symbol} {outcome.predicted_signal} outcome → "
            f"{result} at ₹{outcome.actual_price:,.0f} ({detail})"
        )
        try:
            self._mem.add(
                entry,
                user_id=symbol,
                metadata={"tier": "episodic_outcome", "date": outcome.outcome_date},
            )
            log.info("outcome_memory_added", symbol=symbol, result=result)
        except Exception as e:
            log.warning("outcome_memory_add_failed", symbol=symbol, error=str(e))

    def add_morning_outcome(self, symbol: str, note: MorningNote) -> None:
        """Enrich the latest episodic memory with the morning follow-up status."""
        if self._mem is None:
            return
        entry = f"{symbol}: morning follow-up → {note.status} ('{note.morning_text[:80]}...')"
        try:
            self._mem.add(entry, user_id=symbol, metadata={"tier": "episodic_followup"})
        except Exception as e:
            log.warning("memory_morning_add_failed", symbol=symbol, error=str(e))

    def add_semantic_pattern(self, pattern: str) -> None:
        """Add a cross-stock semantic pattern (global scope, no user_id scoping)."""
        if self._mem is None:
            return
        try:
            self._mem.add(pattern, user_id="__global__", metadata={"tier": "semantic"})
        except Exception as e:
            log.warning("memory_semantic_add_failed", error=str(e))

    def add_procedural_heuristic(self, heuristic: str) -> None:
        """Add a global heuristic extracted from repeated mistakes."""
        if self._mem is None:
            return
        try:
            self._mem.add(heuristic, user_id="__global__", metadata={"tier": "procedural"})
        except Exception as e:
            log.warning("memory_procedural_add_failed", error=str(e))

    def extract_and_store_patterns(self) -> None:
        """Scan recent outcomes and extract cross-stock semantic + procedural patterns.

        Called once per day after the full batch completes (all stocks processed).
        Uses gpt-4o-mini to identify patterns across the last 30 days of outcomes,
        then stores them as semantic/procedural memories for future LLM context.

        Skipped if fewer than 5 evaluated outcomes exist (not enough signal yet).
        Cost: one gpt-4o-mini call per day (~2000 tokens input) = ~$0.10/year.
        """
        if self._mem is None:
            return

        from datetime import date, timedelta

        from analyzer.utils.storage import OutcomeStore

        outcome_store = OutcomeStore()
        all_outcomes = []
        today = date.today()
        for days_back in range(0, 31):
            check_date = today - timedelta(days=days_back)
            daily = outcome_store.load_all(str(check_date))
            all_outcomes.extend(daily)

        evaluated = [o for o in all_outcomes if o.direction_correct is not None]
        if len(evaluated) < 5:
            log.info(
                "pattern_extraction_skipped", reason="insufficient_outcomes", count=len(evaluated)
            )
            return

        lines = []
        for o in evaluated[-60:]:  # cap at 60 to keep prompt size manageable
            result = "CORRECT" if o.direction_correct else "WRONG"
            lines.append(
                f"{o.verdict_date} {o.symbol} {o.predicted_signal} conf={o.predicted_confidence:.2f} "
                f"→ {result} target_hit={o.target_hit} stop_triggered={o.stop_triggered}"
            )
        outcome_text = "\n".join(lines)

        prompt = (
            "You are a quant analyst reviewing recent Indian stock predictions.\n"
            "Here are the outcomes of recent BUY/SELL calls:\n\n"
            f"{outcome_text}\n\n"
            "Identify up to 3 cross-stock PATTERNS (conditions where BUY/SELL reliably succeeds or fails) "
            "and up to 2 HEURISTICS (rules to avoid repeating mistakes).\n"
            "Format your response as:\n"
            "PATTERN: <one-line description>\n"
            "HEURISTIC: <one-line rule>\n"
            "Be specific and concise. Only output PATTERN/HEURISTIC lines, nothing else."
        )

        try:
            from openai import OpenAI

            client = OpenAI()
            response = client.chat.completions.create(
                model=PRIMARY_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_completion_tokens=300,
            )
            content = response.choices[0].message.content or ""
            patterns_added = 0
            heuristics_added = 0
            for line in content.strip().splitlines():
                line = line.strip()
                if line.startswith("PATTERN:"):
                    self.add_semantic_pattern(line[len("PATTERN:") :].strip())
                    patterns_added += 1
                elif line.startswith("HEURISTIC:"):
                    self.add_procedural_heuristic(line[len("HEURISTIC:") :].strip())
                    heuristics_added += 1
            log.info(
                "patterns_extracted",
                outcomes_analyzed=len(evaluated),
                patterns=patterns_added,
                heuristics=heuristics_added,
            )
        except Exception as e:
            log.warning("pattern_extraction_failed", error=str(e))

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_context(self, symbol: str) -> MemoryContext:
        """Retrieve all three memory tiers for a stock and bundle into MemoryContext.

        The query is intentionally broad so Mem0 returns whatever is most relevant
        to the stock's current situation (it handles relevance ranking internally).
        """
        if self._mem is None:
            return MemoryContext()

        episodic: list[str] = []
        semantic: list[str] = []
        procedural: list[str] = []

        try:
            # Mem0 v2.x returns {"results": [...]} dict; v1.x returned a flat list
            def _extract(raw: object) -> list:  # type: ignore[type-arg]
                if isinstance(raw, dict):
                    return raw.get("results", [])  # type: ignore[no-any-return]
                return raw or []  # type: ignore[return-value]

            # Episodic: scoped to this stock
            episodic = [
                r["memory"]
                for r in _extract(
                    self._mem.search(f"analysis for {symbol}", filters={"user_id": symbol}, limit=5)
                )
            ]

            # Semantic + procedural: global scope
            for r in _extract(
                self._mem.search(
                    "stock analysis patterns and heuristics",
                    filters={"user_id": "__global__"},
                    limit=6,
                )
            ):
                tier = r.get("metadata", {}).get("tier", "semantic")
                if tier == "procedural":
                    procedural.append(r["memory"])
                else:
                    semantic.append(r["memory"])
        except Exception as e:
            log.warning("memory_get_failed", symbol=symbol, error=str(e))

        log.info(
            "memory_retrieved",
            symbol=symbol,
            episodic=len(episodic),
            semantic=len(semantic),
            procedural=len(procedural),
        )
        return MemoryContext(episodic=episodic, semantic=semantic, procedural=procedural)

    # ── Formatting ────────────────────────────────────────────────────────────

    @staticmethod
    def _format_episodic(symbol: str, run_date: date, verdict: StockVerdict) -> str:
        """Format a verdict as a compact episodic memory string."""
        price_info = ""
        if verdict.entry:
            price_info = f"entry={verdict.entry} stop={verdict.stop_loss} target={verdict.target}"
        return (
            f"{run_date}: {symbol} {verdict.signal} conf={verdict.confidence:.2f} "
            f'{price_info} — "{verdict.whats_happening[:80]}"'
        )
