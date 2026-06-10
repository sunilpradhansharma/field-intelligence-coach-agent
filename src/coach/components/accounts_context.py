"""T033 — accounts / business-context component (deterministic; LLM only writes wording).

FR-007 / FR-008 / FR-010 / FR-018, Principles I & VI:
- WHAT to surface (the KEY accounts) and the mismatch flag are decided in **pure code** from
  the data. The LLM only phrases the reason text — never the facts or the flag.
- All data is read THROUGH the data-access layer (`get_account_brand_metrics`,
  `get_call_activity`) which is already RBAC-scoped + PRP-scrubbed; the store is never read
  directly. So out-of-scope accounts and PRP-flagged HCPs never appear.
- The cap (how many key rows) and the mismatch threshold come from CONFIG.
- **Per-(account, brand) (I1/I2)**: one `AccountFocus` per (account, brand), labeled by the
  Brand enum's DISPLAY name. Brand strings are never hard-coded.
- Every `AccountFocus` carries a structured reason with the real per-(account, brand) numbers.

Key-account selection (focused, not the whole book): each (account, brand) row gets a
deterministic priority = opportunity level + risk + share-decline magnitude + mismatch; the
top `accounts_max` are surfaced (ties broken by account_id, then brand name).
"""

from __future__ import annotations

from dataclasses import dataclass

from coach.config.settings import Settings, get_settings
from coach.data_access.interface import AccessContext, DataAccess
from coach.schemas import (
    AccountBrandContext,
    AccountBrandMetrics,
    AccountFocus,
    DataPoint,
    OpportunityLevel,
    Reason,
)

PENDING_SUMMARY = "(reason summary pending narration)"

_OPP_WEIGHT = {OpportunityLevel.high: 1.0, OpportunityLevel.med: 0.5, OpportunityLevel.low: 0.0}


@dataclass(frozen=True)
class _Row:
    metrics: AccountBrandMetrics
    calls: int
    calls_trend: float
    has_calls: bool
    mismatch: bool
    priority: float


def _is_mismatch(m: AccountBrandMetrics, calls: int, settings: Settings) -> bool:
    """FR-008: low call activity on a high-opportunity (account, brand)."""
    return (
        m.opportunity_level == OpportunityLevel.high and calls <= settings.mismatch_call_threshold
    )


def _priority(m: AccountBrandMetrics, mismatch: bool) -> float:
    return round(
        _OPP_WEIGHT[m.opportunity_level]
        + (1.0 if m.risk_flag else 0.0)
        + max(0.0, -m.share_trend)  # share-decline magnitude
        + (1.0 if mismatch else 0.0),
        6,
    )


def _reason_for(row: _Row, settings: Settings) -> Reason:
    m, calls = row.metrics, row.calls
    brand = m.brand.value  # DISPLAY name (e.g. "LILETTA") for the DM
    points = [
        DataPoint(
            label=f"{m.account_id}/{brand} market_share",
            value=m.market_share,
            source="AccountBrandMetrics",
        ),
        DataPoint(label="share_trend", value=m.share_trend, source="AccountBrandMetrics"),
        DataPoint(label="volume", value=m.volume, source="AccountBrandMetrics"),
        DataPoint(label="spend", value=m.spend, source="AccountBrandMetrics"),
        DataPoint(label="performance", value=m.performance.value, source="AccountBrandMetrics"),
        DataPoint(
            label="opportunity", value=m.opportunity_level.value, source="AccountBrandMetrics"
        ),
    ]
    if row.has_calls:
        points.append(DataPoint(label="calls", value=calls, source="CallActivity"))
        points.append(DataPoint(label="calls_trend", value=row.calls_trend, source="CallActivity"))
    else:
        # FR-018: report missing data, never fabricate a number.
        points.append(
            DataPoint(
                label="call activity not recorded for this (account, brand)",
                value=0,
                source="CallActivity",
            )
        )
    if row.mismatch:
        thr = settings.mismatch_call_threshold
        points.append(
            DataPoint(
                label=f"mismatch: high opportunity but low calls (calls={calls} <= {thr})",
                value=calls,
                source="CallActivity",
            )
        )
    return Reason(summary=PENDING_SUMMARY, signals=[], data_points=points)


def _account_focus(row: _Row, settings: Settings) -> AccountFocus:
    m = row.metrics
    context = AccountBrandContext(
        market_share=m.market_share,
        share_trend=m.share_trend,
        volume=m.volume,
        spend=m.spend,
        performance=m.performance,
        opportunity_level=m.opportunity_level,
        calls=row.calls,
        calls_trend=row.calls_trend,
    )
    return AccountFocus(
        account_id=m.account_id,
        brand=m.brand,
        context=context,
        mismatch_flag=row.mismatch,
        reason=_reason_for(row, settings),
    )


def accounts_context_for_rep(
    ctx: AccessContext, data: DataAccess, rep_id: str, settings: Settings | None = None
) -> list[AccountFocus]:
    """Return the focused list of key (account, brand) rows for a rep, each with context, a
    mismatch flag, and a data-tied reason. Reads only through `data` (RBAC + PRP enforced).
    Returns an empty list when the rep has no (account, brand) metrics (FR-018)."""
    settings = settings or get_settings()

    metrics = data.get_account_brand_metrics(ctx, rep_id)
    if not metrics:
        return []  # no accounts / no metrics — empty section, no fabrication

    calls_by_pair = {(c.account_id, c.brand): c for c in data.get_call_activity(ctx, rep_id)}

    rows: list[_Row] = []
    for m in metrics:
        ca = calls_by_pair.get((m.account_id, m.brand))
        calls = ca.calls if ca else 0
        calls_trend = ca.calls_trend if ca else 0.0
        mismatch = _is_mismatch(m, calls, settings)
        rows.append(
            _Row(
                metrics=m,
                calls=calls,
                calls_trend=calls_trend,
                has_calls=ca is not None,
                mismatch=mismatch,
                priority=_priority(m, mismatch),
            )
        )

    # Focused: top `accounts_max` by priority; deterministic tie-break (account_id, brand name).
    rows.sort(key=lambda r: (-r.priority, r.metrics.account_id, r.metrics.brand.name))
    return [_account_focus(r, settings) for r in rows[: settings.accounts_max]]
