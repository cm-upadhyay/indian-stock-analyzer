"""Tests for memory/context.py — MemoryContext model and prompt formatting."""

from __future__ import annotations

from analyzer.memory.context import MemoryContext


class TestMemoryContext:
    def test_empty_context_is_empty(self):
        ctx = MemoryContext()
        assert ctx.is_empty() is True

    def test_non_empty_with_episodic(self):
        ctx = MemoryContext(episodic=["2025-01-10: RELIANCE BUY conf=0.72"])
        assert ctx.is_empty() is False

    def test_non_empty_with_semantic(self):
        ctx = MemoryContext(semantic=["RSI<35 + positive news → 71% accuracy"])
        assert ctx.is_empty() is False

    def test_non_empty_with_procedural(self):
        ctx = MemoryContext(procedural=["Avoid BUY on small-caps volume<2×avg"])
        assert ctx.is_empty() is False

    def test_empty_prompt_block_for_empty_context(self):
        ctx = MemoryContext()
        assert ctx.to_prompt_block() == ""

    def test_prompt_block_contains_episodic(self):
        ctx = MemoryContext(episodic=["2025-01-10: RELIANCE BUY conf=0.72"])
        block = ctx.to_prompt_block()
        assert "2025-01-10" in block
        assert "RELIANCE" in block

    def test_prompt_block_contains_semantic(self):
        ctx = MemoryContext(semantic=["RSI<35 + positive news → 71% accuracy"])
        block = ctx.to_prompt_block()
        assert "RSI<35" in block

    def test_prompt_block_contains_procedural(self):
        ctx = MemoryContext(procedural=["Avoid BUY on small-caps volume<2×avg"])
        block = ctx.to_prompt_block()
        assert "small-caps" in block

    def test_prompt_block_has_header_and_footer(self):
        ctx = MemoryContext(episodic=["entry1"])
        block = ctx.to_prompt_block()
        assert "MEMORY CONTEXT" in block
        assert "END MEMORY CONTEXT" in block

    def test_prompt_block_limits_episodic_to_5(self):
        entries = [f"entry_{i}" for i in range(10)]
        ctx = MemoryContext(episodic=entries)
        block = ctx.to_prompt_block()
        # Only last 5 should appear
        for i in range(5, 10):
            assert f"entry_{i}" in block
        # Earlier ones should not
        assert "entry_0" not in block

    def test_prompt_block_limits_semantic_to_3(self):
        patterns = [f"pattern_{i}" for i in range(6)]
        ctx = MemoryContext(semantic=patterns)
        block = ctx.to_prompt_block()
        assert "pattern_0" in block
        assert "pattern_1" in block
        assert "pattern_2" in block
        # Only top 3 shown
        assert "pattern_3" not in block

    def test_all_three_tiers_in_single_block(self):
        ctx = MemoryContext(
            episodic=["past_verdict"],
            semantic=["a_pattern"],
            procedural=["a_heuristic"],
        )
        block = ctx.to_prompt_block()
        assert "past_verdict" in block
        assert "a_pattern" in block
        assert "a_heuristic" in block
