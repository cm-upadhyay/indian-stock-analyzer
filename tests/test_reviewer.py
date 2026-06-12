"""Tests for llm/reviewer.py — reflection reviewer message and overrides."""

from __future__ import annotations

import json

import pandas as pd

from analyzer.data.models import StockVerdict
from analyzer.indicators.fundamental import _analyst_direction
from analyzer.llm import reviewer


def _verdict(**kwargs) -> StockVerdict:  # type: ignore[no-untyped-def]
    defaults = {
        "signal": "BUY",
        "confidence": 0.55,
        "entry": 1000,
        "stop_loss": 950,
        "target": 1050,
        "whats_happening": "x",
        "why_it_matters": "x",
        "watch_out_for": "earnings risk",
        "trader_action": "x",
        "investor_action": "x",
    }
    defaults.update(kwargs)
    return StockVerdict(**defaults)


class TestReviewerMessage:
    """Regression: implicit f-string concatenation + ternary used to truncate the
    reviewer prompt after the Entry line for every BUY/SELL verdict."""

    def _capture_message(self, monkeypatch, verdict):  # type: ignore[no-untyped-def]
        captured: dict[str, str] = {}

        def fake_chat(messages, **kwargs):  # type: ignore[no-untyped-def]
            captured["user"] = messages[1]["content"]
            return json.dumps({"agree": True, "reviewer_note": "fine"}), 10, 5

        monkeypatch.setattr(reviewer.llm_adapter, "chat_completion", fake_chat)
        reviewer.call_reviewer("RELIANCE.NS", verdict, "DATA", 1005.0)
        return captured["user"]

    def test_buy_verdict_message_is_complete(self, monkeypatch):  # type: ignore[no-untyped-def]
        msg = self._capture_message(monkeypatch, _verdict())
        assert "Entry:      ₹1,000" in msg
        assert "Stop-loss:  ₹950" in msg
        assert "Target:     ₹1,050" in msg
        assert "Watch out:  earnings risk" in msg
        assert "Current market price" in msg
        assert "Review this verdict" in msg  # the instruction block must survive

    def test_hold_verdict_message_is_complete(self, monkeypatch):  # type: ignore[no-untyped-def]
        verdict = _verdict(signal="HOLD", entry=None, stop_loss=None, target=None)
        msg = self._capture_message(monkeypatch, verdict)
        assert "Entry:      N/A (HOLD)" in msg
        assert "Review this verdict" in msg


class TestReviewerOverride:
    def test_override_to_hold_clears_price_levels(self, monkeypatch):  # type: ignore[no-untyped-def]
        def fake_chat(messages, **kwargs):  # type: ignore[no-untyped-def]
            return (
                json.dumps(
                    {"agree": False, "override_signal": "HOLD", "reviewer_note": "weak setup"}
                ),
                10,
                5,
            )

        monkeypatch.setattr(reviewer.llm_adapter, "chat_completion", fake_chat)
        final, overridden = reviewer.call_reviewer("X.NS", _verdict(), "DATA", 1000.0)
        assert overridden is True
        assert final.signal == "HOLD"
        assert final.entry is None and final.stop_loss is None and final.target is None

    def test_reviewer_failure_keeps_verdict(self, monkeypatch):  # type: ignore[no-untyped-def]
        def fake_chat(messages, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("model down")

        monkeypatch.setattr(reviewer.llm_adapter, "chat_completion", fake_chat)
        verdict = _verdict()
        final, overridden = reviewer.call_reviewer("X.NS", verdict, "DATA", 1000.0)
        assert final is verdict
        assert overridden is False


class TestAnalystDirection:
    """Regression: this vote was hardcoded NEUTRAL (function never called)."""

    def _recs(self, current_bulls: int, older_bulls: int) -> pd.DataFrame:
        # 10 analysts total per row; row 0 = current month
        rows = []
        for bulls in (current_bulls, older_bulls, older_bulls):
            rows.append(
                {
                    "strongBuy": bulls,
                    "buy": 0,
                    "hold": 10 - bulls,
                    "sell": 0,
                    "strongSell": 0,
                }
            )
        return pd.DataFrame(rows)

    def test_upgrades_vote_buy(self):
        vote, label = _analyst_direction(self._recs(current_bulls=7, older_bulls=4))
        assert vote == "BUY"
        assert "improving" in label

    def test_downgrades_vote_sell(self):
        vote, label = _analyst_direction(self._recs(current_bulls=3, older_bulls=6))
        assert vote == "SELL"

    def test_stable_votes_neutral(self):
        vote, _ = _analyst_direction(self._recs(current_bulls=5, older_bulls=5))
        assert vote == "NEUTRAL"

    def test_missing_recs_neutral(self):
        vote, _ = _analyst_direction(None)
        assert vote == "NEUTRAL"
