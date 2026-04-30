"""MemoryContext — the Pydantic model that bundles all three memory tiers into one object.

The three tiers:
    episodic   — last N raw analyses for this specific stock (what we predicted, what happened)
    semantic   — summarised patterns across many stocks ("RSI-oversold + positive news → 68% accuracy")
    procedural — heuristics extracted from repeated mistakes ("Avoid BUY on small-caps volume<2×avg")

The LLM receives these as a compact ~300-token block prepended to the user message.
Keeping it under 300 tokens is intentional — memory should guide, not dominate the context.
"""

from __future__ import annotations

from pydantic import BaseModel


class MemoryContext(BaseModel):
    """All three memory tiers bundled together, ready to inject into a prompt."""

    # Episodic: list of compact strings like
    #   "2025-01-10: RELIANCE BUY@1320 conf=0.72 → INTACT next day (closed 1341)"
    episodic: list[str] = []

    # Semantic: patterns extracted across stocks
    #   "RSI<35 + positive news → directional accuracy 71% (last 30 days)"
    semantic: list[str] = []

    # Procedural: heuristics from repeated mistakes
    #   "Small-caps with volume < 2× avg have 40% false-positive rate on BUY"
    procedural: list[str] = []

    def is_empty(self) -> bool:
        return not (self.episodic or self.semantic or self.procedural)

    def to_prompt_block(self) -> str:
        """Format the memory context as a prompt-ready block (≤ 300 tokens target).

        Returns empty string if no memories exist yet (first run for a stock).
        """
        if self.is_empty():
            return ""

        parts: list[str] = ["--- MEMORY CONTEXT (from past analyses) ---"]

        if self.episodic:
            parts.append("Past predictions for this stock:")
            for entry in self.episodic[-5:]:  # show at most 5 recent entries
                parts.append(f"  • {entry}")

        if self.semantic:
            parts.append("Patterns observed across all stocks:")
            for pattern in self.semantic[:3]:  # top 3 patterns
                parts.append(f"  • {pattern}")

        if self.procedural:
            parts.append("Learned heuristics (avoid these mistakes):")
            for heuristic in self.procedural[:3]:  # top 3 heuristics
                parts.append(f"  • {heuristic}")

        parts.append("--- END MEMORY CONTEXT ---")
        return "\n".join(parts)
