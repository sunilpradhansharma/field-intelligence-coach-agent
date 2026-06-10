"""T036 — suggested-opener component (deterministic talking points; LLM only writes wording).

FR-009 / FR-010 / FR-011 / FR-018, Principles I & VI:
- The opener is built FROM the already-computed section outputs (the rep's priority reason,
  coaching focus, accounts/mismatch). It introduces **no new data** and fetches nothing from
  the store or retriever — it is a pure function of its inputs.
- The "talking points" (what to raise, and their order) are **selected in code** by a
  deterministic config rule. The LLM later turns them into a natural opening line — it does
  NOT choose the points or invent facts/numbers/brands.
- The opener is a **suggestion only** (FR-011): it carries text + provenance, never an action.
- Every talking point records its provenance (`source` + `ref`) so the opener is explainable.
- Limits come from CONFIG (`opener_max_points`).

Selection (deterministic, ordered):
  1. the top real coaching focus area (skipping the no-gap default),
  2. the most important account — a flagged mismatch first, else the top key account,
  3. the rep's highest-contribution priority signal (why we're riding),
capped at `opener_max_points`. If a rep has no high-priority signals (default focus + no
flagged account), a single positive default talking point is used instead (FR-018) — never
fabricated.
"""

from __future__ import annotations

from coach.config.settings import (
    DEFAULT_FOCUS_AREA,
    DEFAULT_OPENER_POINT,
    Settings,
    get_settings,
)
from coach.schemas import (
    AccountFocus,
    CoachingFocus,
    DataPoint,
    Opener,
    OpenerSource,
    Reason,
    RepRanking,
    TalkingPoint,
)

PENDING_TEXT = "(opening line pending narration)"
PENDING_SUMMARY = "(reason summary pending narration)"


def _provenance_points(points: list[TalkingPoint]) -> list[DataPoint]:
    """Each talking point's provenance, surfaced as the opener's reason data (FR-010)."""
    return [
        DataPoint(label=f"talking point from {p.source.value}", value=p.ref, source=p.source.value)
        for p in points
    ]


def _build_points(
    rep_ranking: RepRanking,
    coaching_focus: list[CoachingFocus],
    accounts: list[AccountFocus],
    settings: Settings,
) -> list[TalkingPoint]:
    points: list[TalkingPoint] = []

    # 1. Top real coaching focus (skip the no-gap default — handled as the FR-018 fallback).
    real_focus = [f for f in coaching_focus if f.focus_area != DEFAULT_FOCUS_AREA]
    if real_focus:
        fa = real_focus[0].focus_area
        points.append(
            TalkingPoint(text=f"Coaching focus: {fa}", source=OpenerSource.coaching_focus, ref=fa)
        )

    # 2. Most important account — a flagged mismatch first, else the top key account.
    acc = next((a for a in accounts if a.mismatch_flag), accounts[0] if accounts else None)
    if acc is not None:
        ref = f"{acc.account_id}/{acc.brand.value}"
        if acc.mismatch_flag:
            text = f"Account to discuss: {ref} — high opportunity but low recent call activity"
        else:
            text = f"Account to review: {ref}"
        points.append(TalkingPoint(text=text, source=OpenerSource.account_mismatch, ref=ref))

    # 3. The rep's highest-contribution priority signal (why we're riding today).
    signals = rep_ranking.reason.signals
    if signals:
        top = max(signals, key=lambda s: s.contribution)
        points.append(
            TalkingPoint(
                text=f"Why this ride: the strongest signal is {top.signal.value}",
                source=OpenerSource.priority,
                ref=rep_ranking.rep_id,
            )
        )

    return points[: settings.opener_max_points]


def build_opener(
    rep_ranking: RepRanking,
    coaching_focus: list[CoachingFocus],
    accounts: list[AccountFocus],
    settings: Settings | None = None,
) -> Opener:
    """Build the suggested opener for a rep from the already-computed section outputs.

    Pure function — introduces no new data. The LLM fills the opening text later (T035)."""
    settings = settings or get_settings()
    points = _build_points(rep_ranking, coaching_focus, accounts, settings)

    if not points:
        # FR-018: no high-priority signals — a positive default, never fabricated.
        points = [
            TalkingPoint(
                text=DEFAULT_OPENER_POINT, source=OpenerSource.default, ref=rep_ranking.rep_id
            )
        ]

    reason = Reason(summary=PENDING_SUMMARY, signals=[], data_points=_provenance_points(points))
    return Opener(text=PENDING_TEXT, talking_points=points, reason=reason)
