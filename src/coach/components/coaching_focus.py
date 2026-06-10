"""T027 — deterministic coaching-focus selection (PURE CODE, no LLM).

FR-005 / FR-010 / FR-018, Principles I & VI:
- WHAT to coach is decided entirely in code by mapping the rep's signals to a FIXED catalog
  of focus areas (config). The LLM NEVER chooses a focus area — it only phrases the reason
  text later (see `coach.llm.narrate.narrate_focus`).
- All data is read THROUGH the data-access layer (already RBAC-scoped + PRP-scrubbed) via the
  shared `compute_rep_signals` — the focus is computed from the SAME numbers as the ranking.
- The catalog, the trigger thresholds, and the max number of focus areas live in CONFIG
  (single, visible source) — never hard-coded here.
- Every focus area carries a structured `reason` (the signal + the real data behind it);
  `reason.summary` is left as the pending sentinel for the LLM to fill (Step 2).

Selection (deterministic):
- A signal triggers a focus when its RAW value >= the configured threshold.
- Strength = the signal's NORMALIZED 0..1 value (same basis as ranking, so strengths are
  comparable across signals — ADR 0001).
- The top `max_focus_areas` triggered focuses are returned, ordered by strength desc, then by
  the fixed signal order (stable tie-break).
- If nothing triggers, a single low-priority default focus is returned with a clear reason
  note (never nothing). A rep with no coaching history is handled gracefully (FR-018).
"""

from __future__ import annotations

from coach.components.signals import RepSignals, compute_rep_signals, row_data_point
from coach.config.settings import DEFAULT_FOCUS_AREA, Settings, get_settings
from coach.data_access.interface import AccessContext, DataAccess
from coach.schemas import (
    CoachingFocus,
    DataPoint,
    Reason,
    SignalContribution,
    SignalName,
)

PENDING_SUMMARY = "(reason summary pending narration)"

# Fixed signal order — the deterministic tie-break when two focuses have equal strength.
_SIGNAL_ORDER = (
    SignalName.declining_share,
    SignalName.low_call_activity,
    SignalName.missed_follow_up,
    SignalName.opportunity_risk,
)
_ORDER_INDEX = {name: i for i, name in enumerate(_SIGNAL_ORDER)}


def _normalized(name: SignalName, raw: float, settings: Settings) -> float:
    cap = settings.ranking_norm_caps[name.value]
    return round(min(raw, cap) / cap, 6) if cap > 0 else 0.0


def _signal_data_points(name: SignalName, sig: RepSignals, top_n: int) -> list[DataPoint]:
    """The real data behind a triggered focus — the per-(account, brand) rows (or coaching
    sessions) that drive this signal. Deterministic order; shows real numbers (FR-010)."""
    if name == SignalName.declining_share:
        rows = sorted(
            (r for r in sig.rows if r.share_drop > 0),
            key=lambda r: (-r.share_drop, r.metrics.account_id, r.metrics.brand.name),
        )
        points = [row_data_point(r, round(r.share_drop, 6)) for r in rows[:top_n]]
    elif name == SignalName.low_call_activity:
        rows = sorted(
            (r for r in sig.rows if r.is_low_call),
            key=lambda r: (r.calls, r.metrics.account_id, r.metrics.brand.name),
        )
        points = [row_data_point(r, r.calls) for r in rows[:top_n]]
    elif name == SignalName.opportunity_risk:
        rows = sorted(
            (r for r in sig.rows if r.is_under_served),
            key=lambda r: (r.metrics.account_id, r.metrics.brand.name),
        )
        points = [row_data_point(r, 1.0) for r in rows[:top_n]]
    else:  # missed_follow_up — from the coaching sessions, not the (account, brand) rows
        missed = sorted(
            (s for s in sig.sessions if not s.follow_up_done), key=lambda s: s.session_id
        )
        points = [
            DataPoint(
                label=(
                    f"session {s.session_id} ({s.date}): "
                    f"{len(s.agreed_actions)} agreed action(s) not followed up"
                ),
                value=len(s.agreed_actions),
                source="CoachingSession",
            )
            for s in missed[:top_n]
        ]
    if not points:
        points = [
            DataPoint(
                label=f"{name.value}: triggered (no row detail)", value=0, source="coaching_focus"
            )
        ]
    return points


def _focus_reason(name: SignalName, sig: RepSignals, settings: Settings) -> Reason:
    raw = sig.raw[name]
    normalized = _normalized(name, raw, settings)
    weight = settings.ranking_weights[name.value]
    signal = SignalContribution(
        signal=name,
        raw_value=raw,
        normalized_value=normalized,
        weight=weight,
        contribution=round(normalized * weight, 6),
    )
    return Reason(
        summary=PENDING_SUMMARY,
        signals=[signal],
        data_points=_signal_data_points(name, sig, settings.top_contributors),
    )


def _no_gap_reason(sig: RepSignals) -> Reason:
    """Reason for the default focus when no signal clears its threshold (FR-018: state what is
    missing/insufficient, never fabricate a gap)."""
    points = [
        DataPoint(label="no signal cleared its trigger threshold", value=0, source="coaching_focus")
    ]
    if not sig.has_history:
        points.append(
            DataPoint(label="no prior coaching history yet", value=0, source="CoachingSession")
        )
    return Reason(summary=PENDING_SUMMARY, signals=[], data_points=points)


def coaching_focus_for_rep(
    ctx: AccessContext, data: DataAccess, rep_id: str, settings: Settings | None = None
) -> list[CoachingFocus]:
    """Return 1-3 deterministic coaching focus areas for a rep, each with a data-tied reason.

    Reads only through `data`. The LLM is NOT involved (wording is added later by narration).
    """
    settings = settings or get_settings()
    sig = compute_rep_signals(ctx, data, rep_id, settings)

    # Candidate focuses: a signal triggers when its raw value clears the config threshold.
    candidates: list[tuple[float, int, SignalName]] = []
    for name in _SIGNAL_ORDER:
        if sig.raw[name] >= settings.focus_thresholds[name.value]:
            strength = _normalized(name, sig.raw[name], settings)
            candidates.append((strength, _ORDER_INDEX[name], name))

    if not candidates:
        return [CoachingFocus(focus_area=DEFAULT_FOCUS_AREA, reason=_no_gap_reason(sig))]

    # Strongest first; ties broken by the fixed signal order (deterministic).
    candidates.sort(key=lambda c: (-c[0], c[1]))
    selected = candidates[: settings.max_focus_areas]
    return [
        CoachingFocus(
            focus_area=settings.focus_catalog[name.value],
            reason=_focus_reason(name, sig, settings),
        )
        for _strength, _idx, name in selected
    ]
