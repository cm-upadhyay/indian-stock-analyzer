"""Moto fixtures — fake AWS services for integration tests.

Each fixture spins up the mocked service, seeds any required state,
and tears down cleanly after the test.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws


@pytest.fixture(autouse=True)
def aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point boto3 at moto's fake endpoints — must set before any boto3 call."""
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "test")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "test")
    monkeypatch.setenv("S3_BUCKET", "analyzer-data-prod")
    monkeypatch.setenv("DYNAMODB_TABLE", "analyzer-subscribers-prod")


@pytest.fixture()
def s3(aws_env: None):  # type: ignore[no-untyped-def]
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="analyzer-data-prod")
        yield client


@pytest.fixture()
def dynamodb(aws_env: None):  # type: ignore[no-untyped-def]
    with mock_aws():
        client = boto3.resource("dynamodb", region_name="us-east-1")
        table = client.create_table(
            TableName="analyzer-subscribers-prod",
            KeySchema=[{"AttributeName": "chat_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "chat_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        yield client
