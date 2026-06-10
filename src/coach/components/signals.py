"""Shared per-rep signal computation (deterministic, PURE CODE) used by the ranking scorer
(T023) and the coaching-focus component (T027).

Both read the rep's per-(account, brand) metrics, call activity, and coaching sessions
THROUGH the data-access layer (already RBAC-scoped + PRP-scrubbed) and roll them up into the
four business signals. Keeping this in one place means the score and the coaching focus are
computed from the SAME numbers. No store access here; no LLM; no non-signal attributes read.
"""

from __future__ import annotations

from dataclasses import dataclass

from coach.config.settings import Settings
from coach.data_access.interface import AccessContext, DataAccess
from coach.schemas import (
    AccountBrandMetrics,
    CoachingSession,
    DataPoint,
    OpportunityLevel,
    Performance,
    SignalName,
)


@dataclass(frozen=True)
class RowSignal:
    """One (account, brand) row's contribution to the signals."""

    metrics: AccountBrandMetrics
    calls: int
    share_drop: float  # max(0, -share_trend) — magnitude of a declining-share row
    is_low_call: bool  # high-opportunity row with calls <= low_call_threshold
    is_under_served: bool  # (risk OR high-opportunity) AND performance == under
    row_score: float  # share_drop + is_low_call + is_under_served (rounded)


@dataclass(frozen=True)
class RepSignals:
    """Everything the score and the coaching focus need, for one rep."""

    rep_id: str
    raw: dict[SignalName, float]  # raw aggregate per signal
    rows: list[RowSignal]  # per-(account, brand) detail (for data points)
    sessions: list[CoachingSession]  # coaching history (for missed-follow-up data points)
    missed_followups: int

    @property
    def has_history(self) -> bool:
        return bool(self.sessions)


def compute_rep_signals(
    ctx: AccessContext, data: DataAccess, rep_id: str, settings: Settings
) -> RepSignals:
    """Aggregate the four signals for one rep from data read through the data-access layer."""
    metrics = data.get_account_brand_metrics(ctx, rep_id)
    calls_by_pair = {(c.account_id, c.brand): c.calls for c in data.get_call_activity(ctx, rep_id)}
    sessions = data.get_coaching_sessions(ctx, rep_id)

    share_decline = 0.0
    low_call = 0
    opp_risk = 0
    rows: list[RowSignal] = []

    for m in metrics:
        calls = calls_by_pair.get((m.account_id, m.brand), 0)
        drop = max(0.0, -m.share_trend)
        is_high = m.opportunity_level == OpportunityLevel.high
        is_low_call = is_high and calls <= settings.low_call_threshold
        is_under_served = (m.risk_flag or is_high) and m.performance == Performance.under
        share_decline += drop
        low_call += int(is_low_call)
        opp_risk += int(is_under_served)
        row_score = round(drop + float(is_low_call) + float(is_under_served), 6)
        rows.append(RowSignal(m, calls, drop, is_low_call, is_under_served, row_score))

    missed = sum(1 for s in sessions if not s.follow_up_done)

    raw = {
        SignalName.declining_share: round(share_decline, 6),
        SignalName.low_call_activity: float(low_call),
        SignalName.missed_follow_up: float(missed),
        SignalName.opportunity_risk: float(opp_risk),
    }
    return RepSignals(rep_id=rep_id, raw=raw, rows=rows, sessions=sessions, missed_followups=missed)


def row_data_point(row: RowSignal, value: float) -> DataPoint:
    """A `DataPoint` for one (account, brand) row. Keyed on the Brand ENUM NAME (stable, e.g.
    `liletta`), NOT the display spelling, so a brand display-spelling change cannot affect the
    structured reason or any fixture. Shows the real underlying numbers."""
    m = row.metrics
    return DataPoint(
        label=(
            f"{m.account_id}/{m.brand.name}: share_trend={m.share_trend}, "
            f"opp={m.opportunity_level.value}, calls={row.calls}, perf={m.performance.value}"
        ),
        value=value,
        source="AccountBrandMetrics+CallActivity",
    )
