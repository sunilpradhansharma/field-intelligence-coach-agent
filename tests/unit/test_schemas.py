"""T019 — schema tests: every recommendation requires a non-empty reason (FR-010)."""

import pytest
from pydantic import ValidationError

from coach.schemas import (
    AccountFocus,
    BusinessMetric,
    CoachingFocus,
    Opener,
    Performance,
    Reason,
    RepRanking,
)


def _reason() -> Reason:
    return Reason(summary="Declining share in high-opportunity accounts.")


def test_reason_summary_must_be_non_empty():
    with pytest.raises(ValidationError):
        Reason(summary="")


def test_reason_valid_with_minimal_fields():
    r = _reason()
    assert r.summary
    assert r.signals == []
    assert r.data_points == []


def test_rep_ranking_requires_reason():
    with pytest.raises(ValidationError):
        RepRanking(rep_id="rep_d1_001", rank=1, total_score=0.8)  # type: ignore[call-arg]


def test_coaching_focus_requires_reason():
    with pytest.raises(ValidationError):
        CoachingFocus(focus_area="Closing new therapy starts")  # type: ignore[call-arg]


def test_account_focus_requires_reason():
    ctx = BusinessMetric(
        account_id="acct_x",
        market_share=0.2,
        share_trend=-0.05,
        volume=1000,
        spend=2000,
        performance=Performance.under,
    )
    with pytest.raises(ValidationError):
        AccountFocus(account_id="acct_x", context=ctx, mismatch_flag=True)  # type: ignore[call-arg]


def test_opener_requires_reason():
    with pytest.raises(ValidationError):
        Opener(text="Let's start with A12.")  # type: ignore[call-arg]


def test_recommendations_construct_with_reason():
    assert RepRanking(rep_id="r1", rank=1, total_score=0.8, reason=_reason()).reason.summary
    assert CoachingFocus(focus_area="Assets", reason=_reason()).reason.summary
    assert Opener(text="Hi", reason=_reason()).reason.summary
