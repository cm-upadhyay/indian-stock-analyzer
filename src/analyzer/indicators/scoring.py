"""31-vote 3-category equal-weight scoring — pure computation, zero external calls.

Takes the three vote dicts (technical 12, fundamental 15, India-specific 4)
and produces a ScoringResult with per-category scores and a combined grade.
"""

from __future__ import annotations

from analyzer.data.models import FundamentalSignals, IndiaSignals, ScoringResult, TechnicalSignals

_GRADE_THRESHOLDS = [
    (0.5, "STRONG BUY"),
    (0.2, "LEAN BUY"),
    (-0.2, "NEUTRAL"),
    (-0.5, "LEAN SELL"),
]


def _tally(votes: dict[str, str]) -> tuple[int, int, int]:
    """Return (buy_count, neutral_count, sell_count)."""
    b = sum(1 for v in votes.values() if v == "BUY")
    n = sum(1 for v in votes.values() if v == "NEUTRAL")
    s = sum(1 for v in votes.values() if v == "SELL")
    return b, n, s


def _score(b: int, s: int, total: int) -> float:
    """Category score from -1 (all sell) to +1 (all buy)."""
    if total == 0:
        return 0.0
    return (b - s) / total


def _grade(score: float) -> str:
    for threshold, label in _GRADE_THRESHOLDS:
        if score >= threshold:
            return label
    return "STRONG SELL"


def _summary(grade: str, b: int, n: int, s: int) -> str:
    return f"{grade:<12s}  {b}B · {n}N · {s}S"


def compute_scoring(
    tech: TechnicalSignals,
    fund: FundamentalSignals,
    india: IndiaSignals,
) -> ScoringResult:
    tb, tn, ts = _tally(tech.votes)
    fb, fn, fs = _tally(fund.votes)
    ib, in_, is_ = _tally(india.votes)

    tech_total = tb + tn + ts
    fund_total = fb + fn + fs
    india_total = ib + in_ + is_

    tech_score = _score(tb, ts, tech_total)
    fund_score = _score(fb, fs, fund_total)
    india_score = _score(ib, is_, india_total)

    # Three categories averaged equally (33/33/33)
    combined_score = (tech_score + fund_score + india_score) / 3

    tech_grade = _grade(tech_score)
    fund_grade = _grade(fund_score)
    india_grade = _grade(india_score)
    combined_grade = _grade(combined_score)

    all_b = tb + fb + ib
    all_n = tn + fn + in_
    all_s = ts + fs + is_
    total_votes = all_b + all_n + all_s

    combined_summary = (
        f"{combined_grade:<12s}  {all_b}B · {all_n}N · {all_s}S  (score: {combined_score:+.2f})"
    )

    return ScoringResult(
        tech_score=tech_score,
        fund_score=fund_score,
        india_score=india_score,
        combined_score=combined_score,
        grade=combined_grade,
        tech_buy=tb,
        tech_neutral=tn,
        tech_sell=ts,
        fund_buy=fb,
        fund_neutral=fn,
        fund_sell=fs,
        india_buy=ib,
        india_neutral=in_,
        india_sell=is_,
        total_buy=all_b,
        total_neutral=all_n,
        total_sell=all_s,
        total_votes=total_votes,
        tech_summary=_summary(tech_grade, tb, tn, ts),
        fund_summary=_summary(fund_grade, fb, fn, fs),
        india_summary=_summary(india_grade, ib, in_, is_),
        combined_summary=combined_summary,
    )
