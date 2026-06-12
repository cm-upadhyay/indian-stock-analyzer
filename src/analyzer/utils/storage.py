"""Storage abstraction — same interface for local JSON (dev) and S3 (prod).

Set STORAGE_BACKEND=s3 and S3_BUCKET_NAME=your-bucket in env to use S3.
Default is local JSON under data/.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import cast

import structlog

from analyzer.data.models import MorningNoteRecord, OutcomeRecord, StockVerdict

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

    def latest_date(self) -> date | None:
        """Return the most recent date that has analysis data, or None if empty."""
        if _backend() == "s3":
            return self._s3_latest_date()
        day_dir = _LOCAL_ROOT / "analyses"
        if not day_dir.exists():
            return None
        dates = sorted(
            (d.name for d in day_dir.iterdir() if d.is_dir()),
            reverse=True,
        )
        for d in dates:
            try:
                return date.fromisoformat(d)
            except ValueError:
                continue
        return None

    def _s3_latest_date(self) -> date | None:
        import boto3

        try:
            resp = boto3.client("s3").list_objects_v2(
                Bucket=_s3_bucket(), Prefix="analyses/", Delimiter="/"
            )
            prefixes = [
                p["Prefix"].rstrip("/").split("/")[-1] for p in resp.get("CommonPrefixes", [])
            ]
            for d in sorted(prefixes, reverse=True):
                try:
                    return date.fromisoformat(d)
                except ValueError:
                    continue
        except Exception as e:
            log.error("s3_list_dates_failed", error=str(e))
        return None

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
                    try:
                        results.append((symbol, StockVerdict.model_validate_json(raw)))
                    except Exception as e:
                        log.warning("storage_corrupt_file", key=key, error=str(e))
        except Exception as e:
            log.error("s3_list_failed", prefix=prefix, error=str(e))
        return results


class OutcomeStore:
    """Read/write outcome records keyed by (verdict_date, symbol).

    S3 path:   outcomes/{verdict_date}/{symbol}.json
    Local path: data/outcomes/{verdict_date}/{symbol}.json
    """

    def save(self, verdict_date: str, symbol: str, outcome: OutcomeRecord) -> None:
        data = outcome.model_dump()
        if _backend() == "s3":
            self._s3_put(f"outcomes/{verdict_date}/{symbol}.json", data)
        else:
            path = _LOCAL_ROOT / "outcomes" / verdict_date / f"{symbol}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2))

    def load(self, verdict_date: str, symbol: str) -> OutcomeRecord | None:
        if _backend() == "s3":
            raw = self._s3_get(f"outcomes/{verdict_date}/{symbol}.json")
        else:
            path = _LOCAL_ROOT / "outcomes" / verdict_date / f"{symbol}.json"
            raw = path.read_text() if path.exists() else None
        if raw is None:
            return None
        return OutcomeRecord.model_validate_json(raw)

    def load_all(self, verdict_date: str) -> list[OutcomeRecord]:
        """Load all outcomes for a given date."""
        if _backend() == "s3":
            return self._s3_load_all_outcomes(verdict_date)
        results: list[OutcomeRecord] = []
        day_dir = _LOCAL_ROOT / "outcomes" / verdict_date
        if not day_dir.exists():
            return results
        for f in day_dir.glob("*.json"):
            try:
                results.append(OutcomeRecord.model_validate_json(f.read_text()))
            except Exception as e:
                log.warning("outcome_store_corrupt", path=str(f), error=str(e))
        return results

    _SUMMARY_KEY = "outcomes/summary.json"

    def save_summary(self, stats: dict) -> None:  # type: ignore[type-arg]
        """Persist precomputed accuracy stats — the API serves this single object
        instead of scanning every outcome file per request (the scan exceeded the
        30s Lambda timeout once record count grew)."""
        if _backend() == "s3":
            self._s3_put(self._SUMMARY_KEY, stats)
        else:
            path = _LOCAL_ROOT / "outcomes" / "summary.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(stats, indent=2))

    def load_summary(self) -> dict[str, object] | None:
        if _backend() == "s3":
            raw = self._s3_get(self._SUMMARY_KEY)
        else:
            path = _LOCAL_ROOT / "outcomes" / "summary.json"
            raw = path.read_text() if path.exists() else None
        if raw is None:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            log.warning("outcome_summary_corrupt", error=str(e))
            return None
        if not isinstance(data, dict):
            return None
        return cast("dict[str, object]", data)

    def _s3_put(self, key: str, data: dict) -> None:  # type: ignore[type-arg]
        import boto3

        boto3.client("s3").put_object(
            Bucket=_s3_bucket(), Key=key, Body=json.dumps(data), ContentType="application/json"
        )

    def _s3_get(self, key: str) -> str | None:
        import boto3

        try:
            resp = boto3.client("s3").get_object(Bucket=_s3_bucket(), Key=key)
            return resp["Body"].read().decode()
        except Exception as e:
            log.warning("s3_outcome_get_failed", key=key, error=str(e))
            return None

    def _s3_load_all_outcomes(self, verdict_date: str) -> list[OutcomeRecord]:
        import boto3

        prefix = f"outcomes/{verdict_date}/"
        results: list[OutcomeRecord] = []
        try:
            resp = boto3.client("s3").list_objects_v2(Bucket=_s3_bucket(), Prefix=prefix)
            for obj in resp.get("Contents", []):
                raw = self._s3_get(obj["Key"])
                if raw:
                    results.append(OutcomeRecord.model_validate_json(raw))
        except Exception as e:
            log.error("s3_outcome_list_failed", prefix=prefix, error=str(e))
        return results


class MorningNoteStore:
    """Read/write morning note records keyed by (date, symbol).

    S3 path:    morning-notes/{date}/{symbol}.json
    Local path: data/morning-notes/{date}/{symbol}.json
    """

    def save(self, run_date: str, symbol: str, record: MorningNoteRecord) -> None:
        data = record.model_dump()
        if _backend() == "s3":
            self._s3_put(f"morning-notes/{run_date}/{symbol}.json", data)
        else:
            path = _LOCAL_ROOT / "morning-notes" / run_date / f"{symbol}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2))

    def load(self, run_date: str, symbol: str) -> MorningNoteRecord | None:
        if _backend() == "s3":
            raw = self._s3_get(f"morning-notes/{run_date}/{symbol}.json")
        else:
            path = _LOCAL_ROOT / "morning-notes" / run_date / f"{symbol}.json"
            raw = path.read_text() if path.exists() else None
        if raw is None:
            return None
        return MorningNoteRecord.model_validate_json(raw)

    def load_all(self, run_date: str) -> list[MorningNoteRecord]:
        """Load all morning notes for a given date."""
        if _backend() == "s3":
            return self._s3_load_all_notes(run_date)
        results: list[MorningNoteRecord] = []
        day_dir = _LOCAL_ROOT / "morning-notes" / run_date
        if not day_dir.exists():
            return results
        for f in day_dir.glob("*.json"):
            try:
                results.append(MorningNoteRecord.model_validate_json(f.read_text()))
            except Exception as e:
                log.warning("morning_note_store_corrupt", path=str(f), error=str(e))
        return results

    def _s3_put(self, key: str, data: dict) -> None:  # type: ignore[type-arg]
        import boto3

        boto3.client("s3").put_object(
            Bucket=_s3_bucket(), Key=key, Body=json.dumps(data), ContentType="application/json"
        )

    def _s3_get(self, key: str) -> str | None:
        import boto3

        try:
            resp = boto3.client("s3").get_object(Bucket=_s3_bucket(), Key=key)
            return resp["Body"].read().decode()
        except Exception as e:
            log.warning("s3_morning_note_get_failed", key=key, error=str(e))
            return None

    def _s3_load_all_notes(self, run_date: str) -> list[MorningNoteRecord]:
        import boto3

        prefix = f"morning-notes/{run_date}/"
        results: list[MorningNoteRecord] = []
        try:
            resp = boto3.client("s3").list_objects_v2(Bucket=_s3_bucket(), Prefix=prefix)
            for obj in resp.get("Contents", []):
                raw = self._s3_get(obj["Key"])
                if raw:
                    results.append(MorningNoteRecord.model_validate_json(raw))
        except Exception as e:
            log.error("s3_morning_note_list_failed", prefix=prefix, error=str(e))
        return results
