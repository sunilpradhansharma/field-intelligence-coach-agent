"""Phase 7 / capability #6 — deterministic theme aggregation (PURE CODE, no LLM).

A leadership roll-up of coaching themes across reps. Two invariants are the point of this phase:

- **PATTERNS / COUNTS ONLY (FR-016):** the output exposes **no named individual reps or
  individually identifiable rep detail** — only themes with counts and shares. This is enforced
  STRUCTURALLY: the `Theme` / `ThemeAggregate` schemas have no rep-identity field, and the code
  here only ever writes COUNTS (never a rep id) into the supporting reason. **Small-cell
  suppression** closes the remaining gap where a small count could identify someone (e.g. a
  1-rep district): any grouping cell — a theme's total, or a per-district count — below
  `Settings.aggregation_min_cell` (a config-visible, tunable privacy control) is masked, never
  shown as a raw small count.
- **RBAC-SCOPED to leadership:** only the **region** and **all** scope levels may aggregate, and
  only across their own region / all regions. A caller below region scope (e.g. a DM) raises
  `ScopeError` — consistent with the rest of the data-access layer (a `403`, indistinguishable
  from not-found, over the API). Region isolation is enforced by the data layer: `get_reps`
  returns only the caller's in-scope reps, so a region caller can never aggregate another region.

Themes come from the SAME source as the per-rep coaching-focus section: this reads each in-scope
rep's focuses via `coaching_focus_for_rep` (which uses the shared `compute_rep_signals` + the
config focus catalog), then counts reps per focus area — so there is no second, drifting
definition of a "theme". All data is read THROUGH the data-access layer (already RBAC-scoped +
PRP-scrubbed); this module never touches a store. The LLM only narrates wording later (Step 2).
"""

from __future__ import annotations

from collections import Counter, defaultdict

from coach.components.coaching_focus import coaching_focus_for_rep
from coach.config.settings import Settings, get_settings
from coach.data_access.interface import AccessContext, DataAccess, ScopeError
from coach.schemas import (
    CoachingFocus,
    DataPoint,
    GeneratedFor,
    Reason,
    ScopeLevel,
    SignalName,
    Theme,
    ThemeAggregate,
)

PENDING_SUMMARY = "(reason summary pending narration)"

# Aggregation is a LEADERSHIP capability: only these scope levels may request it.
_LEADERSHIP_LEVELS = (ScopeLevel.region, ScopeLevel.all_)

_SOURCE = "theme_aggregation"


def _require_leadership_scope(ctx: AccessContext) -> None:
    """Aggregation is region/all only. Anyone below raises `ScopeError` (a `403` over the API,
    indistinguishable from not-found) — a DM never gets an aggregated cross-rep view."""
    if ctx.scope_level not in _LEADERSHIP_LEVELS:
        raise ScopeError(
            "theme aggregation is a leadership view (region / all scope only); "
            f"scope_level={ctx.scope_level} may not aggregate"
        )


def _scope_str(ctx: AccessContext) -> str:
    """The territory the leadership caller is scoped to (region id, or 'all')."""
    return "all" if ctx.scope_level == ScopeLevel.all_ else (ctx.region_id or "")


def _signal_of(focus: CoachingFocus) -> SignalName | None:
    """Which signal this focus maps to — read from the focus's own reason (the triggered
    signal), so the theme's signal is the SAME one the per-rep section computed. The no-gap
    default focus carries no signal -> None."""
    return focus.reason.signals[0].signal if focus.reason.signals else None


def _theme_reason(rep_count: int, total: int, by_district: Counter, min_cell: int) -> Reason:
    """Supporting COUNTS for a theme (explainability) — never rep identities, and with
    **small-cell suppression** so no count can identify an individual (FR-016).

    Suppression is applied at EVERY grouping level that could expose a small group:
    - the theme's own total (`reps with this theme`) is masked if it is below `min_cell`;
    - each per-district cell is shown only if it is at/above `min_cell`; cells below it are
      collapsed into a single masked marker (no raw count, no district id).
    The scope total (`reps in scope`) is the whole leadership scope and is never a small cell.
    NOTE: because small cells are suppressed, the shown per-district counts may not sum to the
    theme total — that is the intended privacy trade-off, not an inconsistency."""
    points = [DataPoint(label="reps in scope", value=total, source=_SOURCE)]
    if rep_count >= min_cell:
        share = round(rep_count / total, 6) if total else 0.0
        points.append(DataPoint(label="reps with this theme", value=rep_count, source=_SOURCE))
        points.append(DataPoint(label="share of reps", value=share, source=_SOURCE))
    else:
        points.append(
            DataPoint(
                label="reps with this theme",
                value=f"fewer than {min_cell} (suppressed)",
                source=_SOURCE,
            )
        )
    # Per-district breakdown: show only cells at/above the threshold; collapse the rest.
    for district_id in sorted(by_district):
        if by_district[district_id] >= min_cell:
            points.append(
                DataPoint(
                    label=f"district {district_id}", value=by_district[district_id], source=_SOURCE
                )
            )
    if any(c < min_cell for c in by_district.values()):
        points.append(
            DataPoint(
                label=f"districts below the reporting threshold ({min_cell}) — suppressed",
                value=f"<{min_cell} each",
                source=_SOURCE,
            )
        )
    return Reason(summary=PENDING_SUMMARY, signals=[], data_points=points)


def aggregate_themes(
    ctx: AccessContext, data: DataAccess, settings: Settings | None = None
) -> ThemeAggregate:
    """Roll the in-scope reps' coaching focuses up into ranked THEMES (patterns + counts).

    Deterministic for a fixed dataset. Reads only through `data`. Raises `ScopeError` if the
    caller is not a leadership (region / all) scope. `reason.summary` is left pending for the
    LLM (Step 2)."""
    settings = settings or get_settings()
    _require_leadership_scope(ctx)  # RBAC: leadership only

    reps = data.get_reps(ctx)  # RBAC-scoped at the data layer (this region's reps / all reps)
    total = len(reps)

    counts: dict[str, int] = defaultdict(int)
    by_district: dict[str, Counter] = defaultdict(Counter)
    signal_of: dict[str, SignalName | None] = {}

    for rep in reps:
        # Same source as the per-rep section: the rep's coaching focuses (shared signals + catalog).
        seen: set[str] = set()
        for focus in coaching_focus_for_rep(ctx, data, rep.rep_id, settings):
            if focus.focus_area in seen:
                continue  # count each rep at most once per theme
            seen.add(focus.focus_area)
            counts[focus.focus_area] += 1
            by_district[focus.focus_area][rep.district_id] += 1
            signal_of.setdefault(focus.focus_area, _signal_of(focus))

    # Ranked: most common first, then theme label asc (stable, deterministic tie-break).
    min_cell = settings.aggregation_min_cell
    themes: list[Theme] = []
    for theme in sorted(counts, key=lambda t: (-counts[t], t)):
        n = counts[theme]
        # Small-cell suppression (FR-016): a theme held by fewer than `min_cell` reps has its
        # raw count + share withheld (masked) so it can't identify an individual.
        suppressed = n < min_cell
        themes.append(
            Theme(
                theme=theme,
                signal=signal_of[theme],
                rep_count=None if suppressed else n,
                rep_share=None if suppressed else (round(n / total, 6) if total else 0.0),
                suppressed=suppressed,
                reason=_theme_reason(n, total, by_district[theme], min_cell),
            )
        )

    return ThemeAggregate(
        generated_for=GeneratedFor(
            user_id=ctx.user_id,
            role=ctx.role,
            scope_level=ctx.scope_level,
            scope=_scope_str(ctx),
        ),
        rep_count=total,
        themes=themes,
    )
