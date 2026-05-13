"""Integration tests for subscriber store — DynamoDB via moto."""

from __future__ import annotations

import pytest
from moto import mock_aws

import analyzer.notify.subscribers as sub


@mock_aws
def test_subscribe_returns_code(dynamodb: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBSCRIBERS_TABLE", "analyzer-subscribers-prod")
    code = sub.subscribe("12345", username="testuser")
    assert len(code) == 6
    assert code.isdigit()


@mock_aws
def test_verify_success(dynamodb: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBSCRIBERS_TABLE", "analyzer-subscribers-prod")
    code = sub.subscribe("12345")
    success, reason = sub.verify("12345", code)
    assert success is True
    assert reason == "ok"


@mock_aws
def test_verify_wrong_code(dynamodb: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBSCRIBERS_TABLE", "analyzer-subscribers-prod")
    sub.subscribe("12345")
    success, reason = sub.verify("12345", "000000")
    assert success is False
    assert reason == "wrong_code"


@mock_aws
def test_verify_already_confirmed(dynamodb: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBSCRIBERS_TABLE", "analyzer-subscribers-prod")
    code = sub.subscribe("12345")
    sub.verify("12345", code)
    success, reason = sub.verify("12345", code)
    assert success is False
    assert reason == "already_confirmed"


@mock_aws
def test_unsubscribe_confirmed(dynamodb: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBSCRIBERS_TABLE", "analyzer-subscribers-prod")
    code = sub.subscribe("12345")
    sub.verify("12345", code)
    removed = sub.unsubscribe("12345")
    assert removed is True


@mock_aws
def test_unsubscribe_unknown(dynamodb: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBSCRIBERS_TABLE", "analyzer-subscribers-prod")
    removed = sub.unsubscribe("99999")
    assert removed is False


@mock_aws
def test_get_confirmed_only_returns_confirmed(
    dynamodb: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUBSCRIBERS_TABLE", "analyzer-subscribers-prod")
    code1 = sub.subscribe("111")
    sub.verify("111", code1)  # confirmed
    sub.subscribe("222")  # stays pending

    confirmed = sub.get_confirmed_chat_ids()
    assert "111" in confirmed
    assert "222" not in confirmed


@mock_aws
def test_verify_not_found(dynamodb: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBSCRIBERS_TABLE", "analyzer-subscribers-prod")
    success, reason = sub.verify("99999", "123456")
    assert success is False
    assert reason == "not_found"
