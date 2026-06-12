"""Phase 8 / capability #5 — Summit optimization (PURE CODE, no LLM).

The Summit "lift" is computed DETERMINISTICALLY in code from a **per-team config formula** (a
representative PLACEHOLDER until the business supplies the real IC-plan logic — see
`config.settings.SummitFormula`). The formula is swappable per team in config; this engine never
hard-codes a team's numbers. The LLM only narrates wording later (Step 3) — it never decides the
lift or the ranking.

How it works:
- Each **team = district**. We aggregate the district's (account, brand) rows — read THROUGH the
  data-access layer (already RBAC-scoped + PRP-scrubbed) — into inputs (mean share, total volume,
  total share-decline magnitude, total calls), apply the team's `SummitFormula`, and get a
  Summit score. Districts are ranked by score (a "Summit ranking position").
- **What-if lift:** for a rep, take their top declining (account, brand) rows, model halting that
  decline, recompute their district's Summit score, re-rank the districts, and report the LIFT
  (e.g. position #6 → #4). The targeted rows ARE the highest-lift opportunities for that rep.

Integrated into the EXISTING normalized rollup as a ranking signal (`components/ranking.py`):
the rep's Summit raw signal = the lift, normalized 0..1 via a config cap and weighted from
config (ADR 0001), so config weights still control influence. OFF by default (weight 0.0).
"""

from __future__ import annotations

from dataclasses import dataclass

from coach.config.settings import Settings, SummitFormula, get_settings
from coach.data_access.interface import AccessContext, DataAccess
from coach.schemas import Brand, DataPoint, Reason, SummitInsight, SummitTarget

PENDING_SUMMARY = "(reason summary pending narration)"
_SOURCE = "summit"


@dataclass(frozen=True)
class _Row:
    """One (account, brand) row's Summit inputs (read through the data-access layer)."""

    account_id: str
    brand: Brand
    market_share: float
    share_trend: float
    volume: float
    calls: int

    @property
    def decline(self) -> float:
        return max(0.0, -self.share_trend)


def _formula_for(settings: Settings, team_id: str) -> SummitFormula:
    """The team's (district's) configured formula, or the shared default — config, never code."""
    return settings.summit_formulas.get(team_id, settings.summit_formulas["default"])


def _score(rows: list[_Row], f: SummitFormula) -> float:
    """A district's Summit score from its rows + the team formula. Pure, deterministic."""
    if not rows:
        return 0.0
    mean_share = sum(r.market_share for r in rows) / len(rows)
    volume = sum(r.volume for r in rows)
    decline = sum(r.decline for r in rows)
    calls = sum(r.calls for r in rows)
    return round(
        f.share_weight * mean_share
        + f.volume_weight * volume
        - f.decline_penalty * decline
        + f.calls_weight * calls,
        6,
    )


def _rows_by_district(
    ctx: AccessContext, data: DataAccess, settings: Settings
) -> dict[str, dict[str, list[_Row]]]:
    """Each in-scope district's (account, brand) rows, grouped by rep — through the data layer
    only (RBAC-scoped + PRP-scrubbed)."""
    out: dict[str, dict[str, list[_Row]]] = {}
    for rep in data.get_reps(ctx):
        calls = {(c.account_id, c.brand): c.calls for c in data.get_call_activity(ctx, rep.rep_id)}
        rows = [
            _Row(
                account_id=m.account_id,
                brand=m.brand,
                market_share=m.market_share,
                share_trend=m.share_trend,
                volume=m.volume,
                calls=calls.get((m.account_id, m.brand), 0),
            )
            for m in data.get_account_brand_metrics(ctx, rep.rep_id)
        ]
        out.setdefault(rep.district_id, {})[rep.rep_id] = rows
    return out


def _district_rows(by_rep: dict[str, list[_Row]]) -> list[_Row]:
    return [r for rows in by_rep.values() for r in rows]


def _positions(scores: dict[str, float]) -> dict[str, int]:
    """Rank districts by Summit score desc (1 = top). Deterministic tie-break by district id."""
    order = sorted(scores, key=lambda d: (-scores[d], d))
    return {district_id: i + 1 for i, district_id in enumerate(order)}


def district_summit_scores(
    ctx: AccessContext, data: DataAccess, settings: Settings | None = None
) -> dict[str, float]:
    """The Summit score for every in-scope district (deterministic; reads through the layer)."""
    settings = settings or get_settings()
    by_district = _rows_by_district(ctx, data, settings)
    return {
        d: _score(_district_rows(by_rep), _formula_for(settings, d))
        for d, by_rep in by_district.items()
    }


def _summit_reason(
    district_id: str, base_pos: int, proj_pos: int, lift: int, targets: list[SummitTarget]
) -> Reason:
    """Supporting raw numbers for a Summit insight (FR-010): the ranking change + the targeted
    (account, brand) movements. Summary is left for the LLM (Step 3)."""
    points = [
        DataPoint(label=f"district {district_id} Summit position", value=base_pos, source=_SOURCE),
        DataPoint(label="projected position after focus", value=proj_pos, source=_SOURCE),
        DataPoint(label="ranking lift (positions gained)", value=lift, source=_SOURCE),
    ]
    for t in targets:
        points.append(
            DataPoint(
                label=(
                    f"{t.account_id}/{t.brand.name}: reduce share decline "
                    f"(trend {t.share_trend} -> {t.projected_share_trend})"
                ),
                value=round(t.decline_reduced, 6),
                source="AccountBrandMetrics",
            )
        )
    if not targets:
        points.append(
            DataPoint(
                label="no declining (account, brand) rows to improve", value=0, source=_SOURCE
            )
        )
    return Reason(summary=PENDING_SUMMARY, signals=[], data_points=points)


def _insight(
    rep_id: str,
    district_id: str,
    rep_rows: list[_Row],
    baseline_scores: dict[str, float],
    settings: Settings,
) -> SummitInsight:
    """Build a rep's Summit insight from the precomputed district baseline (deterministic)."""
    f_home = _formula_for(settings, district_id)
    baseline_pos = _positions(baseline_scores)

    # Highest-lift opportunities: the rep's biggest declining (account, brand) rows.
    declining = sorted(
        (r for r in rep_rows if r.decline > 0),
        key=lambda r: (-r.decline, r.account_id, r.brand.name),
    )[: settings.summit_max_targets]

    # What-if: reducing each targeted row's decline by the TUNABLE per-team `recovery_fraction`
    # (1.0 = full halt/recovery; the assumption lives in config, not here). Only that recovered
    # portion is removed from the district's decline term, so the score rise scales with it.
    recovery = f_home.recovery_fraction
    recovered = sum(r.decline for r in declining) * recovery
    improved = round(baseline_scores[district_id] + f_home.decline_penalty * recovered, 6)
    whatif_scores = {**baseline_scores, district_id: improved}
    whatif_pos = _positions(whatif_scores)
    lift = baseline_pos[district_id] - whatif_pos[district_id]

    targets = [
        SummitTarget(
            account_id=r.account_id,
            brand=r.brand,
            share_trend=r.share_trend,
            # the residual trend after the configured recovery (full recovery -> 0.0)
            projected_share_trend=round(r.share_trend * (1.0 - recovery), 6),
            decline_reduced=round(r.decline * recovery, 6),
        )
        for r in declining
    ]
    return SummitInsight(
        rep_id=rep_id,
        district_id=district_id,
        team_formula=district_id if district_id in settings.summit_formulas else "default",
        baseline_position=baseline_pos[district_id],
        projected_position=whatif_pos[district_id],
        lift=lift,
        targets=targets,
        reason=_summit_reason(
            district_id, baseline_pos[district_id], whatif_pos[district_id], lift, targets
        ),
    )


def summit_insights_for_reps(
    ctx: AccessContext, data: DataAccess, rep_ids: list[str], settings: Settings | None = None
) -> dict[str, SummitInsight]:
    """Summit insight for each of `rep_ids` — computes the district baseline ONCE (efficient).
    Reads only through `data`. Used by the ranking integration."""
    settings = settings or get_settings()
    by_district = _rows_by_district(ctx, data, settings)
    baseline_scores = {
        d: _score(_district_rows(by_rep), _formula_for(settings, d))
        for d, by_rep in by_district.items()
    }
    home_of = {rep_id: d for d, by_rep in by_district.items() for rep_id in by_rep}
    out: dict[str, SummitInsight] = {}
    for rep_id in rep_ids:
        district_id = home_of.get(rep_id)
        if district_id is None:
            continue  # not in scope (the data layer already excluded it)
        rep_rows = by_district[district_id][rep_id]
        out[rep_id] = _insight(rep_id, district_id, rep_rows, baseline_scores, settings)
    return out


def summit_insight_for_rep(
    ctx: AccessContext, data: DataAccess, rep_id: str, settings: Settings | None = None
) -> SummitInsight:
    """A single rep's Summit insight (the what-if lift + highest-lift targets). Standalone."""
    insights = summit_insights_for_reps(ctx, data, [rep_id], settings)
    if rep_id not in insights:
        raise KeyError(rep_id)
    return insights[rep_id]
