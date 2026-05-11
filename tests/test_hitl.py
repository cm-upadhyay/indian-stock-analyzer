"""Tests for HITL approver — trigger conditions and checkpointer backend selection."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from analyzer.data.models import StockVerdict


def _make_verdict(**kwargs) -> StockVerdict:  # type: ignore[no-untyped-def]
    defaults = {
        "signal": "BUY",
        "confidence": 0.72,
        "entry": 1320,
        "stop_loss": 1254,
        "target": 1452,
        "whats_happening": "Price broke above resistance with volume.",
        "why_it_matters": "Institutional accumulation suggests sustained rally.",
        "watch_out_for": "Broad market correction could invalidate the setup.",
        "trader_action": "Enter near 1320. Stop at 1254. Target 1452.",
        "investor_action": "Accumulate on dips below 1330.",
    }
    defaults.update(kwargs)
    return StockVerdict(**defaults)


# ── should_trigger_hitl ───────────────────────────────────────────────────────


class TestShouldTriggerHitl:
    """All tests patch get_flag to "enable_hitl=True" unless stated otherwise."""

    def _call(self, verdict: StockVerdict, **kwargs) -> bool:  # type: ignore[no-untyped-def]
        from analyzer.hitl.approver import should_trigger_hitl

        with patch("analyzer.hitl.approver.get_flag", return_value=True):
            result: bool = should_trigger_hitl(verdict, **kwargs)
            return result

    def test_disabled_flag_returns_false(self) -> None:
        from analyzer.hitl.approver import should_trigger_hitl

        v = _make_verdict(signal="BUY", confidence=0.30)
        with patch("analyzer.hitl.approver.get_flag", return_value=False):
            assert should_trigger_hitl(v) is False

    def test_low_confidence_buy_triggers(self) -> None:
        v = _make_verdict(signal="BUY", confidence=0.40)
        assert self._call(v) is True

    def test_low_confidence_sell_triggers(self) -> None:
        v = _make_verdict(signal="SELL", confidence=0.40)
        assert self._call(v) is True

    def test_hold_low_confidence_does_not_trigger(self) -> None:
        # HOLD is not directional — confidence doesn't matter for HITL
        v = _make_verdict(signal="HOLD", confidence=0.30)
        assert self._call(v) is False

    def test_high_confidence_buy_no_trigger(self) -> None:
        v = _make_verdict(signal="BUY", confidence=0.72)
        assert self._call(v) is False

    def test_reflection_override_triggers(self) -> None:
        v = _make_verdict(signal="BUY", confidence=0.72)
        assert self._call(v, reflection_overrode=True) is True

    def test_nemo_soft_flag_triggers(self) -> None:
        v = _make_verdict(signal="BUY", confidence=0.72)
        assert self._call(v, nemo_soft_flag=True) is True

    def test_large_target_upside_buy_triggers(self) -> None:
        # entry=1000, target=1400 → 40% upside > 30% threshold
        v = _make_verdict(signal="BUY", confidence=0.72, entry=1000, target=1400)
        assert self._call(v) is True

    def test_moderate_upside_no_trigger(self) -> None:
        # entry=1000, target=1250 → 25% upside < 30% threshold
        v = _make_verdict(signal="BUY", confidence=0.72, entry=1000, target=1250)
        assert self._call(v) is False

    def test_large_upside_sell_does_not_trigger_upside_check(self) -> None:
        # Upside check only applies to BUY signals
        v = _make_verdict(signal="SELL", confidence=0.72, entry=1000, target=1400)
        assert self._call(v) is False

    def test_none_entry_skips_upside_check(self) -> None:
        v = _make_verdict(signal="BUY", confidence=0.72, entry=None, target=None)
        assert self._call(v) is False

    def test_exactly_at_confidence_threshold_no_trigger(self) -> None:
        # confidence == threshold is NOT below threshold, so no trigger
        v = _make_verdict(signal="BUY", confidence=0.50)
        assert self._call(v) is False


# ── get_checkpointer ──────────────────────────────────────────────────────────


class TestGetCheckpointer:
    def test_memory_backend_returns_memory_saver(self) -> None:
        from langgraph.checkpoint.memory import MemorySaver

        from analyzer.hitl.approver import get_checkpointer

        with patch("analyzer.hitl.approver.settings") as mock_settings:
            mock_settings.hitl_checkpointer = "memory"
            cp = get_checkpointer()
        assert isinstance(cp, MemorySaver)

    def test_dynamodb_backend_falls_back_to_memory_when_import_fails(self) -> None:
        """DynamoDBSaver import failure must fall back gracefully to MemorySaver."""
        from langgraph.checkpoint.memory import MemorySaver

        from analyzer.hitl.approver import get_checkpointer

        with patch("analyzer.hitl.approver.settings") as mock_settings:
            mock_settings.hitl_checkpointer = "dynamodb"
            mock_settings.hitl_checkpoints_table = "test-table"

            import builtins

            real_import = builtins.__import__

            def _block_dynamo(name, *args, **kwargs):  # type: ignore[no-untyped-def]
                if name == "langgraph_checkpoint_aws":
                    raise ImportError("simulated missing package")
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=_block_dynamo):
                cp = get_checkpointer()

        assert isinstance(cp, MemorySaver)

    def test_dynamodb_backend_returns_dynamodb_saver_when_available(self) -> None:
        """When langgraph_checkpoint_aws is installed, DynamoDBSaver should be returned."""
        pytest.importorskip("langgraph_checkpoint_aws")
        from langgraph_checkpoint_aws import DynamoDBSaver

        from analyzer.hitl.approver import get_checkpointer

        with patch("analyzer.hitl.approver.settings") as mock_settings:
            mock_settings.hitl_checkpointer = "dynamodb"
            mock_settings.hitl_checkpoints_table = "analyzer-hitl-checkpoints-prod"

            with patch.object(DynamoDBSaver, "__init__", return_value=None):
                cp = get_checkpointer()

        assert isinstance(cp, DynamoDBSaver)
