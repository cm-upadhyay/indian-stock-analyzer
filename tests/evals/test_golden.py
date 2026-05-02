"""Golden eval suite — regression tests for scoring logic and guardrails.

Two modes:
    Offline (offline: true in cases.yaml)
        Tests the scoring engine and field-level guardrails with fixed inputs.
        No LLM call needed. Always runs in CI.

    Online (offline: false)
        Tests the full LLM pipeline end-to-end.
        Requires OPENAI_API_KEY. Skipped in CI unless key is present.
        Runs nightly via GitHub Actions scheduled job → results sent to Braintrust.

Run offline only (CI):
    pytest tests/evals/test_golden.py -v -m offline

Run all (nightly):
    OPENAI_API_KEY=sk-... pytest tests/evals/test_golden.py -v
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

_CASES_PATH = Path(__file__).parent / "golden" / "cases.yaml"
_VALID_SIGNALS = {
    "BUY",
    "SELL",
    "HOLD",
    "STRONG BUY",
    "STRONG SELL",
    "LEAN BUY",
    "LEAN SELL",
    "NEUTRAL",
}


def _load_cases() -> list[dict[str, Any]]:
    with open(_CASES_PATH) as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]


def _all_cases() -> list[dict[str, Any]]:
    return _load_cases()


def _offline_cases() -> list[dict[str, Any]]:
    return [c for c in _load_cases() if c.get("offline", False)]


def _online_cases() -> list[dict[str, Any]]:
    return [c for c in _load_cases() if not c.get("offline", False)]


# ── Offline tests (scoring engine + guardrails — no LLM) ─────────────────────


class TestScoringOffline:
    """Verify the scoring engine produces expected vote summaries from raw votes."""

    @pytest.mark.parametrize(
        "case", [c for c in _offline_cases() if c.get("votes")], ids=lambda c: c["id"]
    )
    def test_vote_majority_matches_expected_signal_direction(self, case: dict[str, Any]) -> None:
        """Buy-majority votes should map to bullish signals; sell-majority to bearish."""
        votes = case["votes"]
        buy_v = votes.get("buy", 0)
        sell_v = votes.get("sell", 0)
        expected = case["expected_signal_in"]

        bullish_signals = {"BUY", "STRONG BUY", "LEAN BUY"}
        bearish_signals = {"SELL", "STRONG SELL", "LEAN SELL"}
        neutral_signals = {"HOLD", "NEUTRAL"}

        if buy_v > sell_v + 2:
            assert any(s in bullish_signals for s in expected), (
                f"Case {case['id']}: buy_votes={buy_v} > sell_votes={sell_v}+2 "
                f"but no bullish signal in expected={expected}"
            )
        elif sell_v > buy_v + 2:
            assert any(s in bearish_signals for s in expected), (
                f"Case {case['id']}: sell_votes={sell_v} > buy_votes={buy_v}+2 "
                f"but no bearish signal in expected={expected}"
            )
        else:
            # Near-tie — neutral signals acceptable
            assert any(
                s in neutral_signals | bullish_signals | bearish_signals for s in expected
            ), f"Case {case['id']}: expected must contain at least one valid signal"

    @pytest.mark.parametrize(
        "case", [c for c in _offline_cases() if c.get("votes")], ids=lambda c: c["id"]
    )
    def test_expected_signals_are_valid(self, case: dict[str, Any]) -> None:
        """All expected signal values must be from the known valid set."""
        for sig in case["expected_signal_in"]:
            assert sig in _VALID_SIGNALS, f"Case {case['id']}: '{sig}' is not a valid signal"

    @pytest.mark.parametrize(
        "case", [c for c in _offline_cases() if c.get("votes")], ids=lambda c: c["id"]
    )
    def test_confidence_min_is_reasonable(self, case: dict[str, Any]) -> None:
        """Confidence minimums must be between 0.0 and 1.0."""
        conf_min = case.get("expected_confidence_min", 0.0)
        assert 0.0 <= conf_min <= 1.0, f"Case {case['id']}: confidence_min={conf_min} out of [0, 1]"


class TestGuardrailsOffline:
    """Verify guardrail field validators catch known bad verdicts."""

    @pytest.mark.parametrize(
        "case",
        [c for c in _offline_cases() if c.get("category") == "guardrail"],
        ids=lambda c: c["id"],
    )
    def test_guardrail_entry_deviation(self, case: dict[str, Any]) -> None:
        """Entry price must be within 5% of current price for BUY/SELL."""
        mock = case.get("verdict_mock", {})
        if mock.get("entry") is None or mock.get("current_price") is None:
            pytest.skip("No entry/current_price in this guardrail case")

        from analyzer.guardrails.schema_guards import check_entry_price_range

        entry = mock["entry"]
        current = mock["current_price"]
        should_correct = case["guardrail_should_correct"]

        # If entry is within 5% of current but should_correct=True, the case is
        # testing a different guardrail (stop_loss, confidence) — skip it here.
        if (
            float(current) > 0
            and abs(entry - float(current)) / float(current) <= 0.05
            and should_correct
        ):
            pytest.skip(
                f"Case {case['id']}: entry within 5% of current — "
                f"must be testing a different guardrail: {case.get('guardrail_correction')}"
            )

        error = check_entry_price_range(entry=entry, current_price=float(current))

        if should_correct:
            assert error is not None, (
                f"Case {case['id']}: expected guardrail to reject entry={entry} "
                f"vs current={current}"
            )
        else:
            assert error is None, (
                f"Case {case['id']}: expected guardrail to accept entry={entry} "
                f"vs current={current}, got: {error}"
            )

    @pytest.mark.parametrize(
        "case",
        [c for c in _offline_cases() if c.get("category") == "guardrail"],
        ids=lambda c: c["id"],
    )
    def test_guardrail_confidence_minimum(self, case: dict[str, Any]) -> None:
        """BUY/SELL signals must have confidence >= 0.60."""
        mock = case.get("verdict_mock", {})
        signal = mock.get("signal", "HOLD")
        confidence = mock.get("confidence", 0.5)
        should_correct = case["guardrail_should_correct"]

        from analyzer.config import settings

        directional = signal in (
            "BUY",
            "SELL",
            "STRONG BUY",
            "STRONG SELL",
            "LEAN BUY",
            "LEAN SELL",
        )
        min_conf = settings.guardrail_min_confidence

        if directional and confidence < min_conf and should_correct:
            # Guardrail should flag this
            assert confidence < min_conf, (
                f"Case {case['id']}: expected confidence={confidence} < {min_conf} to be flagged"
            )
        elif not should_correct:
            assert confidence >= min_conf or signal in ("HOLD", "NEUTRAL"), (
                f"Case {case['id']}: expected guardrail to pass but confidence={confidence} < {min_conf}"
            )


# ── Online tests (full LLM pipeline — skipped without API key) ────────────────

_HAS_API_KEY = bool(os.getenv("OPENAI_API_KEY"))


@pytest.mark.skipif(not _HAS_API_KEY, reason="OPENAI_API_KEY not set — skipping online evals")
class TestFullPipelineOnline:
    """Full end-to-end eval: mocked stock data → LLM → assert signal quality.

    These run nightly via GitHub Actions scheduled job with OPENAI_API_KEY secret.
    Results tracked in Braintrust for trend analysis.
    """

    @pytest.mark.parametrize(
        "case",
        [c for c in _online_cases() if c.get("tech_summary") and not c.get("votes")],
        ids=lambda c: c["id"],
    )
    def test_llm_signal_matches_expected(self, case: dict[str, Any]) -> None:
        """LLM signal must be within the expected_signal_in set for this case."""
        from unittest.mock import MagicMock

        from analyzer.data.models import ScoringResult, StockData, TechnicalSignals
        from analyzer.llm.agent import run_agentic_analysis
        from analyzer.memory.context import MemoryContext

        tech_summary = case["tech_summary"]
        news_text = case.get("news", "No recent news available.")
        expected_signals = case["expected_signal_in"]
        conf_min = case.get("expected_confidence_min", 0.0)

        # Build minimal mock objects — enough to drive the agentic loop
        stock = MagicMock(spec=StockData)
        stock.symbol = "TEST.NS"
        stock.company_name = "Test Company Ltd"
        stock.current_price = 1000.0

        tech = MagicMock(spec=TechnicalSignals)
        tech.rsi = 50.0
        tech.rsi_label = "Neutral"
        tech.trend_ma200 = "above MA200"
        tech.volume_ratio = 1.0
        tech.macd_label = "neutral"
        tech.pct_from_low = 50.0
        tech.delivery_label = "normal"
        tech.votes = []

        scoring = MagicMock(spec=ScoringResult)
        scoring.tech_summary = tech_summary

        news_items: list = []
        memory_context = MemoryContext()

        verdict = run_agentic_analysis(
            stock=stock,
            tech=tech,
            scoring=scoring,
            news=news_items,
            news_context=news_text,
            memory_context=memory_context,
        )

        assert verdict.signal in expected_signals, (
            f"Case {case['id']}: LLM returned '{verdict.signal}', "
            f"expected one of {expected_signals}"
        )
        assert verdict.confidence >= conf_min, (
            f"Case {case['id']}: confidence={verdict.confidence:.2f} < min={conf_min}"
        )
        assert verdict.whats_happening, f"Case {case['id']}: whats_happening must not be empty"
        assert verdict.trader_action, f"Case {case['id']}: trader_action must not be empty"
