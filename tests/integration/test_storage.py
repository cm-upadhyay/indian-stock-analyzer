"""Integration tests for AnalysisStore — S3 backend via moto."""

from __future__ import annotations

from datetime import date

import pytest
from moto import mock_aws

from analyzer.data.models import StockVerdict
from analyzer.utils.storage import AnalysisStore


def _verdict() -> StockVerdict:
    return StockVerdict(
        signal="BUY",
        confidence=0.75,
        entry=1400,
        stop_loss=1350,
        target=1600,
        whats_happening="Strong breakout above resistance",
        why_it_matters="Volume confirms institutional buying",
        watch_out_for="Global sell-off risk",
        trader_action="Buy on dip to 1400",
        investor_action="Accumulate with 6-month horizon",
    )


@mock_aws
def test_save_and_load_roundtrip(s3: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET_NAME", "analyzer-data-prod")

    store = AnalysisStore()
    today = date(2026, 5, 12)
    store.save(today, "INFY.NS", _verdict())

    result = store.load(today, "INFY.NS")
    assert result is not None
    assert result.signal == "BUY"
    assert result.confidence == pytest.approx(0.75)


@mock_aws
def test_load_missing_returns_none(s3: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET_NAME", "analyzer-data-prod")

    store = AnalysisStore()
    result = store.load(date(2026, 1, 1), "MISSING.NS")
    assert result is None


@mock_aws
def test_latest_date(s3: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET_NAME", "analyzer-data-prod")

    store = AnalysisStore()
    assert store.latest_date() is None

    store.save(date(2026, 5, 10), "INFY.NS", _verdict())
    store.save(date(2026, 5, 12), "TCS.NS", _verdict())

    assert store.latest_date() == date(2026, 5, 12)


@mock_aws
def test_idempotent_save(s3: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """Saving twice for the same key overwrites — no error."""
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET_NAME", "analyzer-data-prod")

    store = AnalysisStore()
    today = date(2026, 5, 12)
    store.save(today, "INFY.NS", _verdict())

    v2 = _verdict()
    v2.signal = "SELL"
    store.save(today, "INFY.NS", v2)

    result = store.load(today, "INFY.NS")
    assert result is not None
    assert result.signal == "SELL"
