"""Red-team eval suite — adversarial inputs mapped to OWASP LLM Top 10 (2025).

All output-layer tests run on every PR (attack success rate must stay 0).
Input-layer tests (llm-guard) skip in CI unless the package is installed.

Run:
    pytest tests/evals/test_red_team.py -v
"""

from __future__ import annotations

import builtins
import importlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

_CASES_PATH = Path(__file__).parent / "red_team" / "cases.yaml"

_LLM_GUARD_AVAILABLE = False
try:
    import llm_guard  # noqa: F401

    _LLM_GUARD_AVAILABLE = True
except ImportError:
    pass


def _load_cases() -> list[dict[str, Any]]:
    with open(_CASES_PATH) as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]


def _attack_cases() -> list[dict[str, Any]]:
    return [c for c in _load_cases() if c.get("should_block") is True]


def _fp_cases() -> list[dict[str, Any]]:
    return [c for c in _load_cases() if c.get("should_block") is False]


# ── Input layer: ML injection detection (requires llm-guard — ECS Fargate only) ──


@pytest.mark.skipif(
    not _LLM_GUARD_AVAILABLE,
    reason="llm-guard not installed — runs on ECS Fargate pipeline image only",
)
class TestInputInjectionDetection:
    """sanitize_news_text() must detect and block all 27 attack cases."""

    @pytest.mark.parametrize("case", _attack_cases(), ids=lambda c: c["id"])
    def test_injection_is_detected(self, case: dict[str, Any]) -> None:
        import os

        os.environ["INPUT_GUARD_ENABLED"] = "true"
        from analyzer.security.input_guard import sanitize_news_text

        _, flagged = sanitize_news_text(case["input"], symbol="TEST.NS")
        assert flagged is True, (
            f"[{case['id']}] ATTACK NOT BLOCKED — owasp={case['owasp']} "
            f"type={case['attack_type']}\n  input: {case['input'][:120]}"
        )

    @pytest.mark.parametrize("case", _fp_cases(), ids=lambda c: c["id"])
    def test_benign_content_passes(self, case: dict[str, Any]) -> None:
        import os

        os.environ["INPUT_GUARD_ENABLED"] = "true"
        from analyzer.security.input_guard import sanitize_news_text

        _, flagged = sanitize_news_text(case["input"], symbol="TEST.NS")
        assert flagged is False, (
            f"[{case['id']}] FALSE POSITIVE: benign text was blocked\n"
            f"  input: {case['input'][:120]}"
        )


# ── Graceful degradation: no crash without llm-guard ─────────────────────────


class TestInputGuardDegradation:
    """sanitize_news_text() must never raise — returns (text, False) without llm-guard."""

    @pytest.mark.parametrize("case", _attack_cases()[:5], ids=lambda c: c["id"])
    def test_no_crash_without_llm_guard(
        self, case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_import = builtins.__import__

        def mock_import(name: str, *args: object, **kwargs: object) -> object:
            if "llm_guard" in name:
                raise ImportError(f"mocked missing: {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        import analyzer.security.input_guard as guard_mod

        importlib.reload(guard_mod)

        result_text, flagged = guard_mod.sanitize_news_text(case["input"], symbol="TEST.NS")
        assert result_text == case["input"]
        assert flagged is False


# ── Output layer: policy guardrails (always run, no ML deps) ─────────────────


class TestOutputPolicyGuardrails:
    """Pure-Python guardrail functions must reject policy-violating outputs.

    These run in CI on every PR. Even if an injection bypasses the input guard,
    the output layer prevents harmful content reaching the user.
    """

    def test_banned_phrase_detected_in_verdict(self) -> None:
        """check_banned_phrases() must catch 'guaranteed' and 'risk-free'."""
        from analyzer.data.models import StockVerdict
        from analyzer.guardrails.schema_guards import check_banned_phrases

        verdict = MagicMock(spec=StockVerdict)
        verdict.whats_happening = "This is a guaranteed profit opportunity."
        verdict.why_it_matters = "Strong technicals."
        verdict.watch_out_for = "Risk-free investment."
        verdict.trader_action = "Buy immediately."
        verdict.investor_action = "Long-term hold."

        violations = check_banned_phrases(verdict)
        assert len(violations) >= 2, f"Expected >= 2 violations, got {violations}"
        assert any("guaranteed" in v.lower() for v in violations)
        assert any("risk" in v.lower() for v in violations)

    def test_clean_verdict_text_passes(self) -> None:
        """Legitimate analysis text must not be flagged."""
        from analyzer.data.models import StockVerdict
        from analyzer.guardrails.schema_guards import check_banned_phrases

        verdict = MagicMock(spec=StockVerdict)
        verdict.whats_happening = "Technicals suggest potential upside; watch 1250 resistance."
        verdict.why_it_matters = "Strong institutional buying in the sector."
        verdict.watch_out_for = "Broad market selloff could override stock-level positives."
        verdict.trader_action = "Consider entry near 1180 with tight stop."
        verdict.investor_action = "Add on dips if fundamentals remain intact."

        violations = check_banned_phrases(verdict)
        assert violations == [], f"Clean verdict should produce no violations, got {violations}"

    def test_entry_price_deviation_blocked(self) -> None:
        """Entry 20% above current price must be rejected."""
        from analyzer.guardrails.schema_guards import check_entry_price_range

        error = check_entry_price_range(entry=1200, current_price=1000.0)
        assert error is not None, "Entry 20% away should fail (exceeds 5% threshold)"

    def test_entry_price_within_range_passes(self) -> None:
        """Entry within 5% of current price must pass."""
        from analyzer.guardrails.schema_guards import check_entry_price_range

        error = check_entry_price_range(entry=1030, current_price=1000.0)
        assert error is None, f"Entry 3% away should pass, got: {error}"

    def test_low_confidence_buy_blocked(self) -> None:
        """BUY with confidence 0.45 must fail the confidence threshold check."""
        from analyzer.guardrails.schema_guards import check_confidence_threshold

        error = check_confidence_threshold(signal="BUY", confidence=0.45)
        assert error is not None, "BUY with confidence 0.45 should fail (< 0.60 minimum)"

    def test_valid_confidence_buy_passes(self) -> None:
        """BUY with confidence 0.75 must pass."""
        from analyzer.guardrails.schema_guards import check_confidence_threshold

        error = check_confidence_threshold(signal="BUY", confidence=0.75)
        assert error is None, f"BUY confidence 0.75 should pass, got: {error}"

    def test_stop_loss_too_tight_blocked(self) -> None:
        """Stop-loss 0.5% below entry (< 2% minimum) must be rejected."""
        from analyzer.guardrails.schema_guards import check_stop_loss_valid

        error = check_stop_loss_valid(signal="BUY", entry=1000, stop_loss=995)
        assert error is not None, "Stop-loss 0.5% away should fail (minimum is 2%)"

    def test_stop_loss_valid_passes(self) -> None:
        """Stop-loss 3% below entry must pass."""
        from analyzer.guardrails.schema_guards import check_stop_loss_valid

        error = check_stop_loss_valid(signal="BUY", entry=1000, stop_loss=970)
        assert error is None, f"Stop-loss 3% away should pass, got: {error}"

    def test_non_nse_symbol_blocked_by_rail(self) -> None:
        """NSE symbol validator must reject non-Indian exchange symbols."""
        from analyzer.guardrails.nemo_rails.rails import check_symbol_is_nse

        assert check_symbol_is_nse("AAPL") is False
        assert check_symbol_is_nse("BTC-USD") is False
        assert check_symbol_is_nse("OPENAI") is False

    def test_valid_nse_symbol_passes(self) -> None:
        """Valid NSE symbols must pass the validator."""
        from analyzer.guardrails.nemo_rails.rails import check_symbol_is_nse

        assert check_symbol_is_nse("RELIANCE.NS") is True
        assert check_symbol_is_nse("HDFCBANK.NS") is True
        assert check_symbol_is_nse("M&M.NS") is True

    def test_injected_confidence_above_one_detected(self) -> None:
        """Confidence > 1.0 (injected by attacker) must fail validation."""
        import pytest as pt

        # Confidence 1.5 would be produced by a successful injection attack
        # The signal validator won't call check_confidence_threshold with >1,
        # but we verify the pydantic model itself rejects it
        from analyzer.data.models import StockVerdict

        with pt.raises(
            (ValueError, Exception)
        ):  # pydantic or our validator must reject confidence > 1
            StockVerdict(
                signal="BUY",
                confidence=1.5,  # injected: above maximum
                entry=1000,
                stop_loss=950,
                target=1100,
                whats_happening="test",
                why_it_matters="test",
                watch_out_for="test",
                trader_action="test",
                investor_action="test",
                input_tokens=0,
                output_tokens=0,
            )


# ── Dataset integrity ─────────────────────────────────────────────────────────


class TestRedTeamDataset:
    """Verify the red-team dataset itself is complete and well-formed."""

    def test_case_count(self) -> None:
        cases = _load_cases()
        attack = [c for c in cases if c.get("should_block") is True]
        fp = [c for c in cases if c.get("should_block") is False]
        assert len(attack) >= 27, f"Expected >= 27 attack cases, got {len(attack)}"
        assert len(fp) >= 3, f"Expected >= 3 FP check cases, got {len(fp)}"

    def test_owasp_coverage(self) -> None:
        cases = _attack_cases()
        covered = {c["owasp"] for c in cases if c.get("owasp")}
        required = {"LLM01", "LLM02", "LLM06", "LLM07", "LLM08"}
        assert required.issubset(covered), f"Missing OWASP coverage: {required - covered}"

    def test_all_cases_have_required_fields(self) -> None:
        for case in _load_cases():
            assert "id" in case, f"Missing 'id': {case}"
            assert "input" in case, f"Missing 'input' in {case['id']}"
            assert "should_block" in case, f"Missing 'should_block' in {case['id']}"

    def test_no_duplicate_ids(self) -> None:
        ids = [c["id"] for c in _load_cases()]
        assert len(ids) == len(set(ids)), (
            f"Duplicate case IDs found: {set(x for x in ids if ids.count(x) > 1)}"  # noqa: C401
        )
