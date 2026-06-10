"""T011 — coaching-notes retriever (the vector-search path of the single door).

The retriever is NOT a separate trust boundary: it enforces the SAME RBAC scope and the SAME
PRP scrubbing as the structured reads, reusing the existing helpers in `rbac.py`. See
docs/adr/0002-notes-retriever-rbac-prp.md.

- Indexing (build-time, like loading data): reads coaching notes from the store, ties each
  note to the account/HCP it concerns (synthetic + deterministic for the MVP — index metadata
  only, no schema change), embeds the free text, and stores vectors in a `VectorStore`.
- Query (`search_notes`, the single guarded entry point): RBAC-scopes by the caller's
  `AccessContext` (out-of-scope rep -> `ScopeError`) AND drops any note tied to a PRP-flagged
  account, then returns the top-k most similar notes. No path returns un-scoped or PRP notes.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from coach.data_access import rbac
from coach.data_access.interface import AccessContext
from coach.data_access.vector_store import InMemoryVectorStore, VectorStore
from coach.llm.embeddings import EmbeddingProvider
from coach.schemas import CoachingSession


@dataclass(frozen=True)
class NoteChunk:
    """One indexed coaching note + the account/HCP it concerns (for PRP scrubbing)."""

    session: CoachingSession
    account_id: str  # the account this note is about; PRP scrub acts on this


def _note_text(s: CoachingSession) -> str:
    return " ".join([s.notes_text, *s.agreed_actions, *s.observe_next])


def _session_from_row(row: sqlite3.Row) -> CoachingSession:
    return CoachingSession(
        session_id=row["session_id"],
        rep_id=row["rep_id"],
        date=row["date"],
        notes_text=row["notes_text"],
        agreed_actions=json.loads(row["agreed_actions"]),
        observe_next=json.loads(row["observe_next"]),
        follow_up_done=bool(row["follow_up_done"]),
    )


class NotesRetriever:
    """Implements the `Retriever` Protocol (search_notes). Holds a store connection (for the
    RBAC/PRP helpers and build-time indexing), an embeddings provider, and a vector store."""

    def __init__(
        self,
        store,
        embedder: EmbeddingProvider,
        vector_store: VectorStore | None = None,
    ) -> None:
        self._conn: sqlite3.Connection = store._conn
        self._embedder = embedder
        self._index: VectorStore = vector_store or InMemoryVectorStore()
        self._sessions: dict[str, CoachingSession] = {}
        self._account_by_session: dict[str, str] = {}

    # ------------------------------------------------------------------- indexing
    def index(self) -> None:
        """Build the note index from the store (build-time load; the guards run at query)."""
        # Each rep's accounts, ordered — used to tie a note to the account it concerns.
        rep_accounts: dict[str, list[str]] = defaultdict(list)
        for row in self._conn.execute(
            "SELECT rep_id, account_id FROM accounts ORDER BY rep_id, account_id"
        ):
            rep_accounts[row["rep_id"]].append(row["account_id"])

        # Sessions grouped by rep, ordered by session_id (deterministic).
        sessions_by_rep: dict[str, list[CoachingSession]] = defaultdict(list)
        for row in self._conn.execute("SELECT * FROM coaching_sessions ORDER BY session_id"):
            s = _session_from_row(row)
            sessions_by_rep[s.rep_id].append(s)

        chunks: list[NoteChunk] = []
        for rep_id in sorted(sessions_by_rep):
            accounts = rep_accounts.get(rep_id, [])
            for i, s in enumerate(sessions_by_rep[rep_id]):
                account_id = accounts[i % len(accounts)] if accounts else ""
                chunks.append(NoteChunk(session=s, account_id=account_id))

        chunks = self._ensure_prp_coverage(chunks, rep_accounts)

        vectors = self._embedder.embed([_note_text(c.session) for c in chunks])
        for c, vec in zip(chunks, vectors, strict=True):
            self._index.add(
                c.session.session_id, vec, {"rep_id": c.session.rep_id, "account_id": c.account_id}
            )
            self._sessions[c.session.session_id] = c.session
            self._account_by_session[c.session.session_id] = c.account_id

    def _ensure_prp_coverage(
        self, chunks: list[NoteChunk], rep_accounts: dict[str, list[str]]
    ) -> list[NoteChunk]:
        """Deterministically guarantee at least one PRP-tied note exists (so PRP scrubbing is
        testable on the synthetic data). If the account assignment produced none, retie the
        first note (by session_id) whose rep owns a PRP account to that rep's first PRP
        account. Index metadata only — no persisted data changes."""
        prp = rbac.prp_account_ids(self._conn)
        if not prp or any(c.account_id in prp for c in chunks):
            return chunks
        for c in sorted(chunks, key=lambda c: c.session.session_id):
            rep_prp = sorted(a for a in rep_accounts.get(c.session.rep_id, []) if a in prp)
            if rep_prp:
                chunks[chunks.index(c)] = NoteChunk(session=c.session, account_id=rep_prp[0])
                break
        return chunks

    # ---------------------------------------------------------------------- query
    def search_notes(
        self, ctx: AccessContext, rep_id: str, query: str, k: int = 4
    ) -> list[CoachingSession]:
        """Top-k coaching notes for `rep_id`, RBAC-scoped + PRP-scrubbed (the single door)."""
        rbac.require_rep_in_scope(self._conn, ctx, rep_id)  # RBAC -> ScopeError if out of scope
        prp = rbac.prp_account_ids(self._conn)  # PRP scrub set
        qvec = self._embedder.embed([query])[0]

        results: list[CoachingSession] = []
        for session_id, _score, meta in self._index.query(qvec, where={"rep_id": rep_id}):
            if meta["account_id"] in prp:
                continue  # PRP scrub — never return a note tied to a PRP account
            results.append(self._sessions[session_id])
            if len(results) >= k:
                break
        return results

    # ---------------------------------------------------------------- test aids
    def indexed_chunks(self) -> list[NoteChunk]:
        return [
            NoteChunk(session=s, account_id=self._account_by_session[sid])
            for sid, s in self._sessions.items()
        ]

    def prp_tied_session_ids(self) -> set[str]:
        prp = rbac.prp_account_ids(self._conn)
        return {sid for sid, acc in self._account_by_session.items() if acc in prp}
