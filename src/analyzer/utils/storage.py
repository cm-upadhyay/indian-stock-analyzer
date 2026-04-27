"""Storage abstraction — same interface for local JSON (dev) and S3 (prod).

Set STORAGE_BACKEND=s3 and S3_BUCKET_NAME=your-bucket in env to use S3.
Default is local JSON under data/.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import structlog

from analyzer.data.models import StockVerdict

log = structlog.get_logger()

_LOCAL_ROOT = Path("data")


def _backend() -> str:
    """Read at call time so tests can override STORAGE_BACKEND via monkeypatch.setenv."""
    return os.getenv("STORAGE_BACKEND", "local")


def _s3_bucket() -> str:
    return os.getenv("S3_BUCKET_NAME", "")


class AnalysisStore:
    """Read/write per-stock verdicts keyed by (date, symbol)."""

    def save(self, run_date: date, symbol: str, verdict: StockVerdict) -> None:
        data = verdict.model_dump()
        if _backend() == "s3":
            self._s3_put(f"analyses/{run_date}/{symbol}.json", data)
        else:
            path = _LOCAL_ROOT / "analyses" / str(run_date) / f"{symbol}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2))

    def load(self, run_date: date, symbol: str) -> StockVerdict | None:
        if _backend() == "s3":
            raw = self._s3_get(f"analyses/{run_date}/{symbol}.json")
        else:
            path = _LOCAL_ROOT / "analyses" / str(run_date) / f"{symbol}.json"
            raw = path.read_text() if path.exists() else None
        if raw is None:
            return None
        return StockVerdict.model_validate_json(raw)

    def load_all(self, run_date: date) -> list[tuple[str, StockVerdict]]:
        """Load all verdicts for a given date. Returns (symbol, verdict) pairs."""
        if _backend() == "s3":
            return self._s3_load_all(run_date)
        results: list[tuple[str, StockVerdict]] = []
        day_dir = _LOCAL_ROOT / "analyses" / str(run_date)
        if not day_dir.exists():
            return results
        for f in day_dir.glob("*.json"):
            try:
                verdict = StockVerdict.model_validate_json(f.read_text())
                results.append((f.stem, verdict))
            except Exception as e:
                log.warning("storage_corrupt_file", path=str(f), error=str(e))
        return results

    # ── S3 helpers ────────────────────────────────────────────────────────────

    def _s3_put(self, key: str, data: dict) -> None:  # type: ignore[type-arg]
        import boto3

        boto3.client("s3").put_object(
            Bucket=_s3_bucket(),
            Key=key,
            Body=json.dumps(data),
            ContentType="application/json",
        )

    def _s3_get(self, key: str) -> str | None:
        import boto3

        try:
            resp = boto3.client("s3").get_object(Bucket=_s3_bucket(), Key=key)
            return resp["Body"].read().decode()
        except Exception as e:
            log.warning("s3_get_failed", key=key, error=str(e))
            return None

    def _s3_load_all(self, run_date: date) -> list[tuple[str, StockVerdict]]:
        import boto3

        prefix = f"analyses/{run_date}/"
        results: list[tuple[str, StockVerdict]] = []
        try:
            resp = boto3.client("s3").list_objects_v2(Bucket=_s3_bucket(), Prefix=prefix)
            for obj in resp.get("Contents", []):
                key = obj["Key"]
                symbol = key.split("/")[-1].replace(".json", "")
                raw = self._s3_get(key)
                if raw:
                    results.append((symbol, StockVerdict.model_validate_json(raw)))
        except Exception as e:
            log.error("s3_list_failed", prefix=prefix, error=str(e))
        return results
