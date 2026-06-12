"""Brief assembly helpers (T015): the narrate-before-expose guard and the 5-section rubric.

- `assert_narrated` RAISES if an assembled brief still contains any per-section narration
  placeholder (`(reason summary pending narration)`, the opener text, the ride-along opening).
  This makes "narrate before expose" a hard invariant — an un-narrated brief can never be
  returned (ADR 0003).
- `rubric_violations` is the automated 5-section checklist (SC-002): all five sections present
  AND every recommendation carries a visible, non-empty reason. Returns the list of failures
  (empty = pass).
"""

from __future__ import annotations

from coach.components.accounts_context import PENDING_SUMMARY as _ACC_PENDING
from coach.components.coaching_focus import PENDING_SUMMARY as _FOCUS_PENDING
from coach.components.opener import PENDING_SUMMARY as _OPENER_PENDING_SUMMARY
from coach.components.opener import PENDING_TEXT as _OPENER_PENDING_TEXT
from coach.components.ranking import PENDING_SUMMARY as _RANK_PENDING
from coach.components.ride_along_prep import PENDING_OPENING as _RIDE_PENDING_OPENING
from coach.components.ride_along_prep import PENDING_SUMMARY as _RIDE_PENDING_SUMMARY
from coach.schemas import CoachingBrief, RideAlongPrep

# Every per-section narration placeholder. If any of these survives into an assembled brief,
# the brief was not narrated and must NOT be exposed.
PENDING_PLACEHOLDERS: frozenset[str] = frozenset(
    {
        _RANK_PENDING,
        _FOCUS_PENDING,
        _RIDE_PENDING_SUMMARY,
        _RIDE_PENDING_OPENING,
        _ACC_PENDING,
        _OPENER_PENDING_SUMMARY,
        _OPENER_PENDING_TEXT,
    }
)


class BriefNotNarratedError(RuntimeError):
    """Raised when an assembled brief still contains an un-narrated placeholder."""


def _text_fields(brief: CoachingBrief) -> list[tuple[str, str]]:
    """Every user-facing summary/text field in the brief, as (path, value) pairs."""
    fields: list[tuple[str, str]] = []
    for r in brief.ranked_reps:
        fields.append((f"ranked_reps[{r.rep_id}].reason.summary", r.reason.summary))
    for f in brief.coaching_focus:
        fields.append((f"coaching_focus[{f.focus_area}].reason.summary", f.reason.summary))
    rap = brief.ride_along_prep
    fields.append(("ride_along_prep.reason.summary", rap.reason.summary))
    if isinstance(rap, RideAlongPrep):
        fields.append(("ride_along_prep.opening", rap.opening))
    for a in brief.accounts:
        fields.append((f"accounts[{a.account_id}/{a.brand.name}].reason.summary", a.reason.summary))
    fields.append(("opener.text", brief.opener.text))
    fields.append(("opener.reason.summary", brief.opener.reason.summary))
    return fields


def assert_narrated(brief: CoachingBrief) -> None:
    """RAISE if any section still holds a narration placeholder (narrate before expose)."""
    bad = [path for path, val in _text_fields(brief) if val in PENDING_PLACEHOLDERS]
    if bad:
        raise BriefNotNarratedError(
            "narrate-before-expose: un-narrated placeholder(s) in: " + ", ".join(bad)
        )


def rubric_violations(brief: CoachingBrief) -> list[str]:
    """The 5-section checklist rubric (SC-002): all five sections present AND every
    recommendation carries a visible, non-empty reason. Returns the failures (empty = pass)."""
    problems: list[str] = []

    # All five sections present.
    if not brief.ranked_reps:
        problems.append("section 1 (ranked reps) is empty")
    if not brief.selected_rep_id:
        problems.append("no selected rep")
    if not brief.coaching_focus:
        problems.append("section 2 (coaching focus) is empty")
    if brief.ride_along_prep is None:
        problems.append("section 3 (ride-along prep) missing")
    # section 4 (accounts) is present as a list; it may legitimately be empty (FR-018).
    if brief.opener is None:
        problems.append("section 5 (opener) missing")

    # Every recommendation shows a visible, non-empty, non-placeholder reason/text.
    for path, val in _text_fields(brief):
        if not val or not val.strip() or val in PENDING_PLACEHOLDERS:
            problems.append(f"missing/placeholder reason text: {path}")

    return problems
