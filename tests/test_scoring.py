"""Unit tests for scoring.py — pure computation, no I/O."""

from analyzer.data.models import FundamentalSignals, IndiaSignals, TechnicalSignals
from analyzer.indicators.scoring import compute_scoring


def _make_tech(votes: dict[str, str]) -> TechnicalSignals:
    return TechnicalSignals(
        votes=votes,
        rsi=50,
        ma20=100,
        ma50=100,
        ma200=100,
        macd_bullish=True,
        macd_reliable=True,
        volume_ratio=1.0,
        stoch_k=50,
        stoch_d=50,
        bb_pct=0.5,
        williams_r=-50,
        cci=0,
        pct_from_low=50,
        delivery_signal="NEUTRAL",
        delivery_label="normal",
        rsi_label="neutral",
        trend_ma200="uptrend",
        macd_label="bullish",
        vol_label="normal",
        w52_label="mid range",
    )


def _make_fund(votes: dict[str, str]) -> FundamentalSignals:
    return FundamentalSignals(
        votes=votes,
        revenue_growth=None,
        earnings_growth=None,
        trailing_pe=None,
        forward_pe=None,
        peg_ratio=None,
        price_to_book=None,
        profit_margin=None,
        ebitda_margins=None,
        return_on_assets=None,
        debt_to_equity=None,
        current_ratio=None,
        interest_coverage=None,
        operating_cashflow=None,
        free_cashflow=None,
        net_income_ttm=None,
        ocf_quality=None,
        beta=None,
        promoter_stake=None,
        inst_holding=None,
        analyst_count=0,
        analyst_mean=None,
        analyst_label="",
        analyst_upside=None,
        target_mean=None,
        target_low=None,
        target_high=None,
        analyst_direction_vote="NEUTRAL",
        analyst_direction_label="stable",
    )


def _make_india(votes: dict[str, str]) -> IndiaSignals:
    return IndiaSignals(
        votes=votes,
        stock_pcr=None,
        promoter_pledge_pct=None,
        promoter_holding_pct=None,
        institutional_holding_pct=None,
    )


class TestComputeScoring:
    def test_all_buy_gives_strong_buy(self):
        tech_votes = {f"T{i}": "BUY" for i in range(12)}
        fund_votes = {f"F{i}": "BUY" for i in range(15)}
        india_votes = {f"I{i}": "BUY" for i in range(4)}
        result = compute_scoring(
            _make_tech(tech_votes),
            _make_fund(fund_votes),
            _make_india(india_votes),
        )
        assert result.grade == "STRONG BUY"
        assert result.combined_score == 1.0
        assert result.total_buy == 31
        assert result.total_sell == 0

    def test_all_sell_gives_strong_sell(self):
        tech_votes = {f"T{i}": "SELL" for i in range(12)}
        fund_votes = {f"F{i}": "SELL" for i in range(15)}
        india_votes = {f"I{i}": "SELL" for i in range(4)}
        result = compute_scoring(
            _make_tech(tech_votes),
            _make_fund(fund_votes),
            _make_india(india_votes),
        )
        assert result.grade == "STRONG SELL"
        assert result.combined_score == -1.0

    def test_all_neutral_gives_neutral(self):
        tech_votes = {f"T{i}": "NEUTRAL" for i in range(12)}
        fund_votes = {f"F{i}": "NEUTRAL" for i in range(15)}
        india_votes = {f"I{i}": "NEUTRAL" for i in range(4)}
        result = compute_scoring(
            _make_tech(tech_votes),
            _make_fund(fund_votes),
            _make_india(india_votes),
        )
        assert result.grade == "NEUTRAL"
        assert result.combined_score == 0.0

    def test_total_votes_is_31(self):
        tech_votes = {f"T{i}": "BUY" for i in range(12)}
        fund_votes = {f"F{i}": "BUY" for i in range(15)}
        india_votes = {f"I{i}": "BUY" for i in range(4)}
        result = compute_scoring(
            _make_tech(tech_votes),
            _make_fund(fund_votes),
            _make_india(india_votes),
        )
        assert result.total_votes == 31

    def test_equal_weight_across_categories(self):
        # Tech: all BUY (+1.0), Fund: all SELL (-1.0), India: all BUY (+1.0)
        # Combined = (1.0 + -1.0 + 1.0) / 3 = 0.333 → LEAN BUY
        tech_votes = {f"T{i}": "BUY" for i in range(12)}
        fund_votes = {f"F{i}": "SELL" for i in range(15)}
        india_votes = {f"I{i}": "BUY" for i in range(4)}
        result = compute_scoring(
            _make_tech(tech_votes),
            _make_fund(fund_votes),
            _make_india(india_votes),
        )
        assert result.grade == "LEAN BUY"
        assert result.tech_score == 1.0
        assert result.fund_score == -1.0
        assert result.india_score == 1.0

    def test_summary_strings_populated(self):
        tech_votes = {f"T{i}": "BUY" for i in range(12)}
        fund_votes = {f"F{i}": "NEUTRAL" for i in range(15)}
        india_votes = {f"I{i}": "SELL" for i in range(4)}
        result = compute_scoring(
            _make_tech(tech_votes),
            _make_fund(fund_votes),
            _make_india(india_votes),
        )
        assert "BUY" in result.tech_summary
        assert "NEUTRAL" in result.fund_summary
        assert "SELL" in result.india_summary
        assert "B" in result.combined_summary
