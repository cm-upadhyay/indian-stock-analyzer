"""Tests for utils/budget.py — daily token budget guard."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _make_budget(limit: int = 1000, tmp_dir: str = "") -> object:  # type: ignore[no-untyped-def]
    """Create a DailyBudget with a temp directory so tests don't write to data/."""
    from analyzer.utils.budget import DailyBudget

    budget = DailyBudget(daily_limit=limit)
    if tmp_dir:
        from datetime import date

        budget._path = Path(tmp_dir) / f"{date.today()}.json"
    return budget


class TestDailyBudget:
    def test_initial_usage_is_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            budget = _make_budget(tmp_dir=tmp)
            assert budget.usage() == 0

    def test_consume_within_budget_returns_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            budget = _make_budget(limit=1000, tmp_dir=tmp)
            assert budget.consume(500) is True

    def test_consume_over_budget_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            budget = _make_budget(limit=1000, tmp_dir=tmp)
            budget.consume(800)
            assert budget.consume(400) is False  # 1200 > 1000

    def test_remaining_after_partial_consumption(self):
        with tempfile.TemporaryDirectory() as tmp:
            budget = _make_budget(limit=1000, tmp_dir=tmp)
            budget.consume(300)
            assert budget.remaining() == 700

    def test_remaining_never_negative(self):
        with tempfile.TemporaryDirectory() as tmp:
            budget = _make_budget(limit=100, tmp_dir=tmp)
            budget.consume(500)  # over-consume
            assert budget.remaining() == 0

    def test_is_exhausted_after_full_consumption(self):
        with tempfile.TemporaryDirectory() as tmp:
            budget = _make_budget(limit=100, tmp_dir=tmp)
            budget.consume(100)
            assert budget.is_exhausted() is True

    def test_not_exhausted_initially(self):
        with tempfile.TemporaryDirectory() as tmp:
            budget = _make_budget(tmp_dir=tmp)
            assert budget.is_exhausted() is False

    def test_usage_accumulates_across_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            budget = _make_budget(limit=10000, tmp_dir=tmp)
            budget.consume(300)
            budget.consume(200)
            budget.consume(100)
            assert budget.usage() == 600

    def test_json_file_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            budget = _make_budget(limit=1000, tmp_dir=tmp)
            budget.consume(250)
            assert budget._path.exists()
            data = json.loads(budget._path.read_text())
            assert data["tokens"] == 250

    def test_corrupt_file_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            budget = _make_budget(tmp_dir=tmp)
            budget._path.parent.mkdir(parents=True, exist_ok=True)
            budget._path.write_text("not valid json")
            assert budget.usage() == 0
