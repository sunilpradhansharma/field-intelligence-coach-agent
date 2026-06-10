"""RBAC scoping (T008) + PRP scrubbing helpers (T008A) for the data-access layer.

Enforced at the DATA-ACCESS LAYER (Principle V / FR-013), never the UI. Access is scoped
by the caller's `AccessContext.scope_level` — which is derived from the role via the single
config source `config.ROLE_SCOPE_LEVELS` — NOT by hard-coded role names:

    self     -> a rep: only their own records
    district -> a DM: only their own district
    region   -> region-level roles (RD, RBE): all districts in their region
    all       -> top sales role (Head of Sales): everything

All non-rep roles have FULL access within their scope (no read-only). A read for data
outside the caller's scope raises `ScopeError`.

PRP scrubbing (FR-020): HCPs/accounts flagged ``prp = true`` (and any dependent rows, e.g.
their call activity / brand metrics) are removed on EVERY read before results are returned,
regardless of scope level, so no PRP HCP ever reaches a field user.

RETRIEVER PRP HOOK: the vector-store `Retriever` (T011) is NOT built yet. When it is, it
MUST also scrub PRP — reuse `prp_account_ids()` to drop any note/result tied to a PRP
account before returning it. Do not return retriever results without this scrub.
"""

from __future__ import annotations

import sqlite3

from coach.data_access.interface import AccessContext, ScopeError
from coach.schemas import ScopeLevel


# --------------------------------------------------------------------------- RBAC (T008)
def scoped_rep_ids(conn: sqlite3.Connection, ctx: AccessContext) -> list[str]:
    """The rep ids the caller may read, ordered, per their scope level."""
    level = ctx.scope_level
    if level == ScopeLevel.all_:
        rows = conn.execute("SELECT rep_id FROM reps ORDER BY rep_id").fetchall()
    elif level == ScopeLevel.region:
        rows = conn.execute(
            "SELECT r.rep_id FROM reps r JOIN districts d ON r.district_id = d.district_id "
            "WHERE d.region_id = ? ORDER BY r.rep_id",
            (ctx.region_id,),
        ).fetchall()
    elif level == ScopeLevel.district:
        rows = conn.execute(
            "SELECT rep_id FROM reps WHERE district_id = ? ORDER BY rep_id",
            (ctx.district_id,),
        ).fetchall()
    elif level == ScopeLevel.self_:
        rows = conn.execute(
            "SELECT rep_id FROM reps WHERE rep_id = ? ORDER BY rep_id",
            (ctx.rep_id,),
        ).fetchall()
    else:
        rows = []
    return [r["rep_id"] for r in rows]


def rep_in_scope(conn: sqlite3.Connection, ctx: AccessContext, rep_id: str) -> bool:
    """True if `rep_id` exists AND is within the caller's scope level."""
    level = ctx.scope_level
    if level == ScopeLevel.self_:
        return rep_id == ctx.rep_id
    row = conn.execute("SELECT district_id FROM reps WHERE rep_id = ?", (rep_id,)).fetchone()
    if row is None:
        return False  # unknown rep -> treat as out of scope (do not reveal existence)
    if level == ScopeLevel.all_:
        return True
    district_id = row["district_id"]
    if level == ScopeLevel.district:
        return district_id == ctx.district_id
    if level == ScopeLevel.region:
        d = conn.execute(
            "SELECT 1 FROM districts WHERE district_id = ? AND region_id = ?",
            (district_id, ctx.region_id),
        ).fetchone()
        return d is not None
    return False


def require_rep_in_scope(conn: sqlite3.Connection, ctx: AccessContext, rep_id: str) -> None:
    """Raise `ScopeError` if `rep_id` is outside the caller's scope (or does not exist)."""
    if not rep_in_scope(conn, ctx, rep_id):
        raise ScopeError(
            f"rep {rep_id!r} is outside the caller's scope (scope_level={ctx.scope_level})"
        )


# ----------------------------------------------------------------- PRP scrubbing (T008A)
def prp_account_ids(conn: sqlite3.Connection) -> set[str]:
    """Account ids flagged PRP (prescriber data restriction).

    Reused by every read to scrub PRP HCPs before returning results (FR-020). The future
    vector-store `Retriever` (T011) MUST also call this to drop PRP-tied notes/results.
    """
    rows = conn.execute("SELECT account_id FROM accounts WHERE prp = 1").fetchall()
    return {r["account_id"] for r in rows}
