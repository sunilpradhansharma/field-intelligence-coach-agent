"""T023 — deterministic rep prioritization scorer (PURE CODE, no LLM).

Principles I & VI / FR-002, FR-012, FR-017:
- The ranking is computed entirely in code. The LLM NEVER decides ranks or scores — it
  only writes `reason.summary` later (T024).
- Same data -> same ranks and scores, every time (deterministic; documented tie-break).
- All data is read THROUGH the data-access layer (already RBAC-scoped + PRP-scrubbed). The
  scorer never touches a store directly.
- Weights and thresholds come from CONFIG (single, visible source) — never hard-coded here.
- Only the four business signals affect the score; non-signal attributes (e.g. tenure, name)
  are never read.

Rollup (per rep, aggregating across the rep's (account, brand) rows) — each produces a RAW
aggregate, which is then NORMALIZED to 0..1 via a config-visible cap before weighting:
  * declining_share   = sum of negative share_trend magnitude across rows
  * low_call_activity = count of high-opportunity rows whose calls <= low_call_threshold
  * missed_follow_up  = count of coaching sessions with follow_up_done == False
  * opportunity_risk  = count of (risk OR high-opportunity) rows that are under-served
                        (performance == under)
normalized = min(raw, cap) / cap   (cap from Settings.ranking_norm_caps; saturates at 1.0)
score = sum(normalized_value * fixed_weight) using weights + caps from config. Because every
signal is on the same 0..1 scale, the fixed weights alone control relative influence.
Rationale + options considered: docs/adr/0001-signal-normalization.md.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from coach.components.signals import RowSignal, compute_rep_signals, row_data_point
from coach.components.summit import summit_insights_for_reps
from coach.config.settings import Settings, get_settings
from coach.data_access.interface import AccessContext, DataAccess
from coach.schemas import (
    DataPoint,
    Reason,
    RepRanking,
    SignalContribution,
    SignalName,
)

# The deterministic scorer fills the structured `reason` (signals + data points) but leaves
# the human prose to T024. The schema requires a non-empty `Reason.summary`, so we use this
# explicit sentinel; T024 narration overwrites ONLY this field.
PENDING_SUMMARY = "(reason summary pending narration)"

# The four CORE business signals — iterated explicitly (never dict order) so output is
# deterministic. Summit (capability #5) is an OPTIONAL 5th signal, appended only when configured
# with a non-zero weight (see `_apply_summit`); these four are the MVP ranking and are unchanged
# when Summit is off.
_SIGNAL_ORDER = (
    SignalName.declining_share,
    SignalName.low_call_activity,
    SignalName.missed_follow_up,
    SignalName.opportunity_risk,
)
CORE_SIGNALS = _SIGNAL_ORDER  # the four MVP signals (Summit is added on top only when weighted)


@dataclass(frozen=True)
class _Scored:
    rep_id: str
    total_score: float
    opportunity_risk_value: float  # for the documented tie-break
    reason: Reason


def _score_rep(ctx: AccessContext, data: DataAccess, rep_id: str, settings: Settings) -> _Scored:
    sig = compute_rep_signals(ctx, data, rep_id, settings)

    signals: list[SignalContribution] = []
    total = 0.0
    for name in _SIGNAL_ORDER:
        raw = sig.raw[name]
        cap = settings.ranking_norm_caps[name.value]
        normalized = round(min(raw, cap) / cap, 6) if cap > 0 else 0.0
        weight = settings.ranking_weights[name.value]
        contribution = round(normalized * weight, 6)
        signals.append(
            SignalContribution(
                signal=name,
                raw_value=raw,
                normalized_value=normalized,
                weight=weight,
                contribution=contribution,
            )
        )
        total += contribution

    reason = Reason(
        summary=PENDING_SUMMARY,
        signals=signals,
        data_points=_top_contributor_points(sig.rows, settings.top_contributors),
    )
    return _Scored(
        rep_id=rep_id,
        total_score=round(total, 6),
        opportunity_risk_value=sig.raw[SignalName.opportunity_risk],
        reason=reason,
    )


def _top_contributor_points(rows: list[RowSignal], top_n: int) -> list[DataPoint]:
    """Top contributing (account, brand) pairs (by row_score). Data points are keyed on the
    Brand ENUM NAME (stable), not the display spelling, via `row_data_point`."""
    # Deterministic order: highest contribution first, then account_id, then brand name.
    ordered = sorted(rows, key=lambda r: (-r.row_score, r.metrics.account_id, r.metrics.brand.name))
    points = [row_data_point(r, r.row_score) for r in ordered[:top_n] if r.row_score > 0]
    if not points:
        # Edge case (no high-need signals / no rows / no history): say so, never fabricate.
        points = [DataPoint(label="no high-need signals for this rep", value=0, source="ranking")]
    return points


def _apply_summit(
    ctx: AccessContext,
    data: DataAccess,
    settings: Settings,
    scored: list[_Scored],
    weight: float,
) -> list[_Scored]:
    """Fold the Summit opportunity (capability #5) into the rep scores via the SAME normalized
    rollup (ADR 0001): raw = the district ranking LIFT (positions gained), normalized 0..1 via the
    config cap, contribution = normalized × the config weight. The deterministic lift is computed
    in `components/summit.py` (per-team config formula) — the LLM is NOT involved. Appends a
    Summit `SignalContribution` + the targeted (account, brand) movements to each rep's reason."""
    insights = summit_insights_for_reps(ctx, data, [s.rep_id for s in scored], settings)
    cap = settings.ranking_norm_caps[SignalName.summit_opportunity.value]
    out: list[_Scored] = []
    for s in scored:
        insight = insights.get(s.rep_id)
        if insight is None:
            out.append(s)
            continue
        raw = float(insight.lift)
        normalized = round(min(raw, cap) / cap, 6) if cap > 0 else 0.0
        contribution = round(normalized * weight, 6)
        summit_signal = SignalContribution(
            signal=SignalName.summit_opportunity,
            raw_value=raw,
            normalized_value=normalized,
            weight=weight,
            contribution=contribution,
        )
        new_reason = s.reason.model_copy(
            update={
                "signals": [*s.reason.signals, summit_signal],
                "data_points": [*s.reason.data_points, *insight.reason.data_points],
            }
        )
        out.append(
            replace(s, total_score=round(s.total_score + contribution, 6), reason=new_reason)
        )
    return out


def rank_reps(
    ctx: AccessContext, data: DataAccess, settings: Settings | None = None
) -> list[RepRanking]:
    """Rank the in-scope reps by need for coaching (highest score = rank 1).

    Reads only through `data` (the data-access layer). Deterministic for a fixed dataset.
    Tie-break (documented, data-model.md): total_score desc, opportunity_risk desc, rep_id asc.

    The four core signals are always scored; the **Summit** opportunity (capability #5) is folded
    in ONLY when `ranking_weights["summit_opportunity"]` is non-zero (OFF by default), so the MVP
    ranking is unchanged unless Summit is configured on.
    """
    settings = settings or get_settings()
    scored = [_score_rep(ctx, data, rep.rep_id, settings) for rep in data.get_reps(ctx)]
    summit_weight = settings.ranking_weights.get(SignalName.summit_opportunity.value, 0.0)
    if summit_weight > 0:
        scored = _apply_summit(ctx, data, settings, scored, summit_weight)
    scored.sort(key=lambda s: (-s.total_score, -s.opportunity_risk_value, s.rep_id))
    return [
        RepRanking(rep_id=s.rep_id, rank=i + 1, total_score=s.total_score, reason=s.reason)
        for i, s in enumerate(scored)
    ]
