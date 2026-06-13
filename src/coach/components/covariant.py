"""Phase 9 / capability #4 — covariant analysis (PURE CODE, no LLM).

A SIMPLE, TRANSPARENT association between rep-behavior variables and a configured "success"
measure, across the in-scope (account, brand) data. It is computed DETERMINISTICALLY in code as
plain counts / rates / lift — NOT a black-box model — and the LLM only narrates wording (Step 3).

HONESTY (and stated in the output): this is a transparent association on SYNTHETIC data; a richer
covariant model would need real data. When there is too little data it returns a clear
**insufficient-data** state and claims no association (FR-018) — it never fabricates one.

What it computes:
- The **success measure** is a config DEFAULT ASSUMPTION (`Settings.success_measure`,
  `SuccessMeasure`) — by default a (account, brand) row "wins" if its share is **rising** AND its
  performance is **on/above target**. Tunable per config, never hard-coded here.
- Two behavior variables (reused, no drift): `call_activity` (calls above the existing
  `low_call_threshold`) and `spend_support` (spend at/above the config `covariant_spend_threshold`,
  a placeholder proxy for "use of approved assets / spend").
- For each variable: the success rate when it is high vs low (+ counts) and the **lift**.
- The **optimal blend**: the combination of variables with the highest observed success rate
  (with a minimum support), with the supporting numbers.

All data is read THROUGH the data-access layer (already RBAC-scoped + PRP-scrubbed), reusing
`compute_rep_signals` so the rows / call pairing are the SAME as the rest of the engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from coach.components.signals import compute_rep_signals
from coach.config.settings import Settings, SuccessMeasure, get_settings
from coach.data_access.interface import AccessContext, DataAccess
from coach.schemas import (
    AccountBrandMetrics,
    CovariantAnalysis,
    CovariantBlend,
    CovariantVariableFinding,
    DataPoint,
    Performance,
    Reason,
)

PENDING_SUMMARY = "(reason summary pending narration)"
_SOURCE = "covariant"

# The behavior variables (fixed order -> deterministic output). Reused definitions, no drift.
_VARIABLES = ("call_activity", "spend_support")

_HONESTY_NOTE = (
    "simple, transparent association on synthetic data; a richer covariant model needs real data"
)


def meets_success_measure(metrics: AccountBrandMetrics, measure: SuccessMeasure) -> bool:
    """Whether one (account, brand) row meets the configured success measure (the single, visible
    definition — read from config, never hard-coded). Default: rising share AND on/above target."""
    rising = metrics.share_trend > measure.min_share_trend
    on_target = (not measure.require_on_or_above_target) or metrics.performance in (
        Performance.on,
        Performance.over,
    )
    return rising and on_target


def describe_success_measure(measure: SuccessMeasure) -> str:
    """A plain-language description of the configured measure (transparency)."""
    parts = [f"rising share (share_trend > {measure.min_share_trend})"]
    if measure.require_on_or_above_target:
        parts.append("performance on/above target")
    return " and ".join(parts)


@dataclass(frozen=True)
class _AnalysisRow:
    success: bool
    variables: dict[str, bool]


def _collect_rows(ctx: AccessContext, data: DataAccess, settings: Settings) -> list[_AnalysisRow]:
    """Every in-scope (account, brand) row as (success, behavior variables) — read through the
    data-access layer (RBAC + PRP), reusing `compute_rep_signals` (same rows / call pairing)."""
    measure = settings.success_measure
    rows: list[_AnalysisRow] = []
    for rep in data.get_reps(ctx):
        sig = compute_rep_signals(ctx, data, rep.rep_id, settings)
        for rs in sig.rows:
            m = rs.metrics
            rows.append(
                _AnalysisRow(
                    success=meets_success_measure(m, measure),
                    variables={
                        "call_activity": rs.calls > settings.low_call_threshold,
                        "spend_support": m.spend >= settings.covariant_spend_threshold,
                    },
                )
            )
    return rows


def _rate(rows: list[_AnalysisRow]) -> float:
    return round(sum(1 for r in rows if r.success) / len(rows), 6) if rows else 0.0


def _finding(variable: str, rows: list[_AnalysisRow]) -> CovariantVariableFinding:
    """One variable's transparent high-vs-low success rates + lift (plain counts/rates)."""
    high = [r for r in rows if r.variables[variable]]
    low = [r for r in rows if not r.variables[variable]]
    return CovariantVariableFinding(
        variable=variable,
        n_high=len(high),
        success_rate_high=_rate(high),
        n_low=len(low),
        success_rate_low=_rate(low),
        lift=round(_rate(high) - _rate(low), 6),
    )


def _optimal_blend(rows: list[_AnalysisRow], min_support: int) -> CovariantBlend | None:
    """The variable combination with the highest observed success rate among combinations whose
    support (rows where all its variables are true) is at least `min_support`. Deterministic
    tie-break: higher success rate, then larger support, then the sorted variable tuple."""
    candidates: list[tuple[float, int, tuple[str, ...]]] = []
    for size in range(1, len(_VARIABLES) + 1):
        for combo in combinations(_VARIABLES, size):
            matched = [r for r in rows if all(r.variables[v] for v in combo)]
            if len(matched) >= min_support:
                candidates.append((_rate(matched), len(matched), combo))
    if not candidates:
        return None
    rate, n, combo = max(candidates, key=lambda c: (c[0], c[1], tuple(sorted(c[2]))))
    return CovariantBlend(variables=list(combo), n=n, success_rate=rate)


def _reason(
    measure_desc: str,
    n: int,
    overall: float,
    findings: list[CovariantVariableFinding],
    blend: CovariantBlend | None,
) -> Reason:
    """Supporting numbers for the analysis (FR-010): the success measure, the rows analyzed, each
    variable's high-vs-low success rates + lift, and the optimal blend — all transparent."""
    points = [
        DataPoint(label="success measure", value=measure_desc, source=_SOURCE),
        DataPoint(label="(account, brand) rows analyzed", value=n, source=_SOURCE),
        DataPoint(label="overall success rate", value=overall, source=_SOURCE),
    ]
    for f in findings:
        points.append(
            DataPoint(
                label=f"{f.variable}: success rate high vs low",
                value=(
                    f"{f.success_rate_high} (n={f.n_high}) vs {f.success_rate_low} "
                    f"(n={f.n_low}); lift {f.lift}"
                ),
                source=_SOURCE,
            )
        )
    if blend is not None:
        points.append(
            DataPoint(
                label="optimal blend",
                value=(
                    f"{' + '.join(blend.variables)}: success rate "
                    f"{blend.success_rate} (n={blend.n})"
                ),
                source=_SOURCE,
            )
        )
    else:
        points.append(
            DataPoint(
                label="no variable combination met the minimum support", value=0, source=_SOURCE
            )
        )
    points.append(DataPoint(label="note", value=_HONESTY_NOTE, source=_SOURCE))
    return Reason(summary=PENDING_SUMMARY, signals=[], data_points=points)


def _insufficient(measure_desc: str, n: int, min_rows: int) -> CovariantAnalysis:
    """A clear insufficient-data state — no association is claimed (FR-018)."""
    reason = Reason(
        summary=PENDING_SUMMARY,
        signals=[],
        data_points=[
            DataPoint(label="success measure", value=measure_desc, source=_SOURCE),
            DataPoint(label="(account, brand) rows analyzed", value=n, source=_SOURCE),
            DataPoint(
                label=f"insufficient data — need at least {min_rows} rows; no association computed",
                value=n,
                source=_SOURCE,
            ),
            DataPoint(label="note", value=_HONESTY_NOTE, source=_SOURCE),
        ],
    )
    return CovariantAnalysis(
        success_measure=measure_desc,
        rows_analyzed=n,
        success_rate_overall=0.0,
        variable_findings=[],
        optimal_blend=None,
        insufficient_data=True,
        reason=reason,
    )


def covariant_analysis(
    ctx: AccessContext, data: DataAccess, settings: Settings | None = None
) -> CovariantAnalysis:
    """Compute the transparent covariant analysis across the caller's in-scope (account, brand)
    rows. Deterministic for a fixed dataset. Reads only through `data` (RBAC + PRP). Returns an
    insufficient-data state when there are fewer than `covariant_min_rows` rows."""
    settings = settings or get_settings()
    measure_desc = describe_success_measure(settings.success_measure)
    rows = _collect_rows(ctx, data, settings)
    n = len(rows)
    if n < settings.covariant_min_rows:
        return _insufficient(measure_desc, n, settings.covariant_min_rows)

    overall = _rate(rows)
    findings = [_finding(var, rows) for var in _VARIABLES]
    blend = _optimal_blend(rows, settings.covariant_min_support)
    return CovariantAnalysis(
        success_measure=measure_desc,
        rows_analyzed=n,
        success_rate_overall=overall,
        variable_findings=findings,
        optimal_blend=blend,
        insufficient_data=False,
        reason=_reason(measure_desc, n, overall, findings, blend),
    )
