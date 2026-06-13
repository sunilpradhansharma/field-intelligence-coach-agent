"""T030 — ride-along prep component (deterministic; the LLM only writes wording).

FR-006 / FR-010 / FR-018, Principles I & VI:
- WHAT to surface is decided in **pure code** from the data. The LLM writes only the summary +
  opening suggestion, never the facts.
- **Note free-text content comes via the RETRIEVER** (`Retriever.search_notes`, the guarded
  entry point that already enforces RBAC scope + PRP scrubbing). The **structured
  coaching-session fields** (agreed actions, what-to-observe-next) come via the **data-access
  store** (`get_coaching_sessions`). Both calls pass the same `AccessContext`, so scope + PRP
  still apply — scope is never widened, and the store / vector index are never read directly.
- The "most recent N" limit comes from CONFIG.
- Every surfaced item records its provenance (session_id, date, and whether it came from the
  structured store or the retriever).

Edge cases (FR-018): a rep with no surfaceable coaching history returns an `EmptyState` (never
fabricated); a session missing a field (e.g. no observe-next recorded) yields a clear
"not recorded" note for that field.
"""

from __future__ import annotations

from coach.components.coaching_focus import coaching_focus_for_rep
from coach.config.settings import Settings, get_settings
from coach.data_access.interface import AccessContext, DataAccess, Retriever
from coach.schemas import (
    CoachingSession,
    DataPoint,
    EmptyState,
    NoteSource,
    PriorActionItem,
    PriorNote,
    Reason,
    RideAlongPrep,
)

PENDING_SUMMARY = "(reason summary pending narration)"
PENDING_OPENING = "(opening suggestion pending narration)"
NO_HISTORY_MESSAGE = "No prior coaching history yet."
RESTRICTED_MESSAGE = "No prior coaching history to show."
NOT_RECORDED = "not recorded"


def _empty_state(rep_id: str, message: str) -> EmptyState:
    reason = Reason(
        summary=PENDING_SUMMARY,
        signals=[],
        data_points=[DataPoint(label=message, value=0, source="ride_along_prep")],
    )
    return EmptyState(rep_id=rep_id, message=message, reason=reason)


def _recall_query(ctx: AccessContext, data: DataAccess, rep_id: str, settings: Settings) -> str:
    """The retriever query: the rep's current coaching focus areas (so note recall is relevant
    to what we'd coach). Deterministic; falls back to a base phrase."""
    focuses = coaching_focus_for_rep(ctx, data, rep_id, settings)
    return " ".join(f.focus_area for f in focuses) or "coaching prioritization"


def _action_items(sessions: list[CoachingSession], field: str) -> list[PriorActionItem]:
    """Flatten a structured list field (agreed_actions / observe_next) across the sessions,
    from the STRUCTURED store. A session with the field empty yields a 'not recorded' note."""
    items: list[PriorActionItem] = []
    for s in sessions:
        values = getattr(s, field)
        if values:
            items.extend(
                PriorActionItem(
                    session_id=s.session_id,
                    date=s.date,
                    text=v,
                    source=NoteSource.structured_store,
                )
                for v in values
            )
        else:
            items.append(
                PriorActionItem(
                    session_id=s.session_id,
                    date=s.date,
                    text=NOT_RECORDED,
                    source=NoteSource.structured_store,
                )
            )
    return items


def ride_along_prep_for_rep(
    ctx: AccessContext,
    data: DataAccess,
    retriever: Retriever,
    rep_id: str,
    settings: Settings | None = None,
) -> RideAlongPrep | EmptyState:
    """Assemble ride-along prep for one rep. Reads only through `data` and `retriever` (both
    RBAC-scoped + PRP-scrubbed). Returns an `EmptyState` when there is no surfaceable history."""
    settings = settings or get_settings()

    # Structured sessions (RBAC-scoped) — authoritative for agreed_actions / observe_next.
    sessions = data.get_coaching_sessions(ctx, rep_id)
    if not sessions:
        return _empty_state(rep_id, NO_HISTORY_MESSAGE)

    # Note free-text via the RETRIEVER (the RBAC + PRP-guarded entry point). A PRP-tied note is
    # dropped by the retriever, so it never appears in `recalled_by_id`.
    query = _recall_query(ctx, data, rep_id, settings)
    recalled = retriever.search_notes(ctx, rep_id, query, k=settings.ride_along_max_notes * 5 + 5)
    recalled_by_id = {s.session_id: s for s in recalled}

    # LOAD-BEARING PRP/RBAC GATE: a session surfaces ONLY if the retriever returned it. This
    # scrubs the WHOLE record — its free text AND its structured fields (agreed_actions /
    # observe_next) AND its session_id — because everything below is derived from `surfaceable`.
    # `get_coaching_sessions` itself is RBAC-scoped but does not PRP-filter note bodies, so this
    # intersection is what enforces PRP on the structured fields too (ADR 0002). Do not bypass it.
    surfaceable = [s for s in sessions if s.session_id in recalled_by_id]
    if not surfaceable:
        return _empty_state(rep_id, RESTRICTED_MESSAGE)

    # Most recent N (date desc, then session_id desc — deterministic).
    recent = sorted(surfaceable, key=lambda s: (s.date, s.session_id), reverse=True)[
        : settings.ride_along_max_notes
    ]

    prior_notes = [
        PriorNote(
            session_id=s.session_id,
            date=s.date,
            text=recalled_by_id[s.session_id].notes_text,  # free text via the retriever
            source=NoteSource.retriever,
        )
        for s in recent
    ]
    agreed_actions = _action_items(recent, "agreed_actions")  # structured store
    observe_next = _action_items(recent, "observe_next")  # structured store

    reason = Reason(
        summary=PENDING_SUMMARY,
        signals=[],
        data_points=[
            DataPoint(
                label=f"{len(prior_notes)} prior note(s) via the RBAC+PRP-scrubbed retriever",
                value=len(prior_notes),
                source="retriever",
            ),
            DataPoint(
                label=f"agreed actions + observe-next from {len(recent)} session(s) (store)",
                value=len(recent),
                source="structured_store",
            ),
        ],
    )
    return RideAlongPrep(
        rep_id=rep_id,
        prior_notes=prior_notes,
        agreed_actions=agreed_actions,
        observe_next=observe_next,
        opening=PENDING_OPENING,
        reason=reason,
    )
