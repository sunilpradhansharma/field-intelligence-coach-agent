"""T019 — schema tests: every recommendation requires a non-empty reason (FR-010)."""

import pytest
from pydantic import ValidationError

from coach.schemas import (
    AccountBrandContext,
    AccountFocus,
    Brand,
    CoachingFocus,
    Opener,
    OpportunityLevel,
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
    ctx = AccountBrandContext(
        market_share=0.2,
        share_trend=-0.05,
        volume=1000,
        spend=2000,
        performance=Performance.under,
        opportunity_level=OpportunityLevel.high,
        calls=1,
        calls_trend=-0.3,
    )
    with pytest.raises(ValidationError):
        AccountFocus(  # type: ignore[call-arg]
            account_id="acct_x", brand=Brand.liletta, context=ctx, mismatch_flag=True
        )


def test_opener_requires_reason():
    with pytest.raises(ValidationError):
        Opener(text="Let's start with A12.")  # type: ignore[call-arg]


def test_recommendations_construct_with_reason():
    assert RepRanking(rep_id="r1", rank=1, total_score=0.8, reason=_reason()).reason.summary
    assert CoachingFocus(focus_area="Assets", reason=_reason()).reason.summary
    assert Opener(text="Hi", reason=_reason()).reason.summary
