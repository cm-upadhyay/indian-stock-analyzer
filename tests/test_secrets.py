"""Tests for utils/secrets.py — only the non-production path is testable without AWS."""

from analyzer.utils.secrets import load_secrets_from_ssm


def test_skips_outside_production(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    load_secrets_from_ssm()  # must return without error and without touching boto3


def test_skips_when_environment_is_dev(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    load_secrets_from_ssm()  # must return without error
