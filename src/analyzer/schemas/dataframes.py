"""Pandera DataFrame schemas — validate every yfinance/nsetools result at the boundary.

Why this exists: yfinance returns different shapes depending on the stock, date, and
NSE session. A delisted ticker returns an empty frame. A stock split on a boundary date
returns a row where High < Low. These silently produce wrong indicators. Pandera catches
them at the boundary before any computation touches the data.

Usage:
    from analyzer.schemas.dataframes import validate_ohlcv
    df = validate_ohlcv(raw_df, symbol="RELIANCE.NS")
"""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
import structlog
from pandera.pandas import Column, DataFrameSchema

log = structlog.get_logger()

# ── OHLCV schema ──────────────────────────────────────────────────────────────
# Every yfinance OHLCV download must pass this before entering indicators/.

OHLCVSchema = DataFrameSchema(
    columns={
        "Open": Column(float, pa.Check.gt(0), nullable=False),
        "High": Column(float, pa.Check.gt(0), nullable=False),
        "Low": Column(float, pa.Check.gt(0), nullable=False),
        "Close": Column(float, pa.Check.gt(0), nullable=False),
        # Volume can be 0 on F&O expiry days or for ETFs; allow NaN for data gaps
        "Volume": Column(float, pa.Check.ge(0), nullable=True),
    },
    checks=[
        # Split/merge glitches sometimes produce High < Low on the boundary date
        pa.Check(
            lambda df: (df["High"] >= df["Low"]).all(),
            error="High must be >= Low for all rows",
        ),
        # MA-200 needs 200 rows; our indicators also need at least 50
        pa.Check(
            lambda df: len(df) >= 50,
            error="Need at least 50 rows — check if symbol is correct or data period is too short",
        ),
    ],
    coerce=True,  # cast int columns to float automatically
)


def validate_ohlcv(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Validate an OHLCV DataFrame and return it clean.

    Drops any rows where Close is NaN (gaps in data feed) before validating.
    Raises ValueError if the frame still fails schema checks.
    """
    # Drop rows where Close is NaN — some brokers emit placeholder rows
    clean = df.dropna(subset=["Close"])

    try:
        return OHLCVSchema.validate(clean, lazy=True)
    except pa.errors.SchemaErrors as exc:
        failures = exc.failure_cases[["check", "failure_case"]].to_dict(orient="records")
        log.error("ohlcv_validation_failed", symbol=symbol, failures=failures[:5])
        raise ValueError(f"OHLCV validation failed for {symbol}: {failures[:3]}") from exc
    except pa.errors.SchemaError as exc:
        log.error("ohlcv_validation_failed", symbol=symbol, error=str(exc))
        raise ValueError(f"OHLCV validation failed for {symbol}: {exc}") from exc
