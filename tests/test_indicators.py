"""Unit tests for indicators/ — zero network calls, zero mocks.

All indicator functions are pure Python: data in, vote structs out.
These tests run without any API keys or internet access.
"""

import pandas as pd
import pytest

from analyzer.indicators.india import compute_india_signals
from analyzer.indicators.scoring import _grade, _score, _tally
from analyzer.indicators.technical import compute_technical

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_ohlcv(prices: list[float]) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from a close price series."""
    n = len(prices)
    return pd.DataFrame(
        {
            "Close": prices,
            "Open": [p * 0.99 for p in prices],
            "High": [p * 1.01 for p in prices],
            "Low": [p * 0.98 for p in prices],
            "Volume": [1_000_000] * n,
        }
    )


def _rising_prices(n: int = 252) -> list[float]:
    return [1000 + i * 2 for i in range(n)]


def _falling_prices(n: int = 252) -> list[float]:
    return [2000 - i * 2 for i in range(n)]


# ── Scoring helpers ───────────────────────────────────────────────────────────


class TestTally:
    def test_all_buy(self):
        votes = {"A": "BUY", "B": "BUY", "C": "BUY"}
        assert _tally(votes) == (3, 0, 0)

    def test_mixed(self):
        votes = {"A": "BUY", "B": "NEUTRAL", "C": "SELL"}
        b, n, s = _tally(votes)
        assert b == 1 and n == 1 and s == 1

    def test_empty(self):
        assert _tally({}) == (0, 0, 0)


class TestScore:
    def test_all_buy(self):
        assert _score(10, 0, 10) == 1.0

    def test_all_sell(self):
        assert _score(0, 10, 10) == -1.0

    def test_neutral(self):
        assert _score(5, 5, 10) == 0.0

    def test_zero_total(self):
        assert _score(0, 0, 0) == 0.0


class TestGrade:
    def test_strong_buy(self):
        assert _grade(0.6) == "STRONG BUY"

    def test_lean_buy(self):
        assert _grade(0.3) == "LEAN BUY"

    def test_neutral(self):
        assert _grade(0.0) == "NEUTRAL"

    def test_lean_sell(self):
        assert _grade(-0.3) == "LEAN SELL"

    def test_strong_sell(self):
        assert _grade(-0.6) == "STRONG SELL"

    def test_boundary_lean_buy(self):
        assert _grade(0.2) == "LEAN BUY"

    def test_boundary_strong_buy(self):
        assert _grade(0.5) == "STRONG BUY"


# ── Technical indicators ──────────────────────────────────────────────────────


class TestComputeTechnical:
    def _run(self, prices: list[float], delivery_signal: str = "NEUTRAL") -> object:
        ohlcv = _make_ohlcv(prices)
        current = prices[-1]
        high = max(prices)
        low = min(prices)
        pct_from_low = (current - low) / (high - low) * 100
        return compute_technical(
            ohlcv=ohlcv,
            current_price=current,
            high_52w=high,
            low_52w=low,
            pct_from_low=pct_from_low,
            delivery_signal=delivery_signal,
            delivery_label="test",
        )

    def test_returns_12_votes(self):
        result = self._run(_rising_prices())
        assert len(result.votes) == 12

    def test_all_votes_are_valid(self):
        result = self._run(_rising_prices())
        for vote in result.votes.values():
            assert vote in ("BUY", "NEUTRAL", "SELL")

    def test_rising_trend_bullish_ma(self):
        result = self._run(_rising_prices(252))
        # In a strong uptrend: price > MA50 and MA20 > MA50 → both BUY
        assert result.votes["Price_vs_MA50"] == "BUY"
        assert result.votes["MA20_vs_MA50"] == "BUY"

    def test_falling_trend_bearish_ma(self):
        result = self._run(_falling_prices(252))
        assert result.votes["Price_vs_MA50"] == "SELL"
        assert result.votes["MA20_vs_MA50"] == "SELL"

    def test_delivery_signal_passed_through(self):
        result = self._run(_rising_prices(), delivery_signal="BUY")
        assert result.votes["Delivery_Pct"] == "BUY"
        assert result.delivery_signal == "BUY"

    def test_rsi_range(self):
        result = self._run(_rising_prices())
        assert 0 <= result.rsi <= 100

    def test_volume_ratio_positive(self):
        result = self._run(_rising_prices())
        assert result.volume_ratio > 0

    def test_pct_from_low_in_range(self):
        result = self._run(_rising_prices())
        assert 0 <= result.pct_from_low <= 100


# ── India-specific signals ────────────────────────────────────────────────────


class TestComputeIndiaSignals:
    def test_no_data_all_neutral(self):
        result = compute_india_signals([], [], None, None)
        for vote in result.votes.values():
            assert vote == "NEUTRAL"

    def test_low_pcr_bullish(self):
        # PCR = 0.5 (more calls than puts) → BUY
        oc = [
            {"CE": {"openInterest": 1000}, "PE": {"openInterest": 500}},
        ]
        result = compute_india_signals(oc, [], 0.6, 0.4)
        assert result.votes["Stock_PCR"] == "BUY"
        assert result.stock_pcr == pytest.approx(0.5)

    def test_high_pcr_bearish(self):
        # PCR = 1.5 (more puts than calls) → SELL
        oc = [
            {"CE": {"openInterest": 1000}, "PE": {"openInterest": 1500}},
        ]
        result = compute_india_signals(oc, [], 0.6, 0.4)
        assert result.votes["Stock_PCR"] == "SELL"

    def test_low_pledge_bullish(self):
        pledge = [{"pledgedSharesPerc": 2.0}]
        result = compute_india_signals([], pledge, 0.5, 0.35)
        assert result.votes["Promoter_Pledge"] == "BUY"

    def test_high_pledge_bearish(self):
        pledge = [{"pledgedSharesPerc": 30.0}]
        result = compute_india_signals([], pledge, 0.5, 0.35)
        assert result.votes["Promoter_Pledge"] == "SELL"

    def test_good_promoter_holding_bullish(self):
        # 51% promoter stake (decimal 0.51) → in 35–70% range → BUY
        result = compute_india_signals([], [], 0.51, 0.35)
        assert result.votes["Promoter_Holding"] == "BUY"

    def test_high_institutional_bullish(self):
        # 40% institutional → BUY
        result = compute_india_signals([], [], 0.5, 0.40)
        assert result.votes["Institutional_Holdings"] == "BUY"

    def test_low_institutional_bearish(self):
        # 5% institutional → SELL
        result = compute_india_signals([], [], 0.5, 0.05)
        assert result.votes["Institutional_Holdings"] == "SELL"
