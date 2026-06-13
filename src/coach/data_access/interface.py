"""The data-access interface — the single seam every component reads through.

This module defines the *contracts* only:
- `AccessContext`: who is asking (role + territory). RBAC enforcement on top of this is
  a LATER task (T008); the context is defined here so the interface is stable.
- `DataAccess`: structured reads (reps, accounts, activity, metrics, sessions).
- `Retriever`: coaching-notes RAG (implemented in a later phase with embeddings).
- `ScopeError`: raised when a read is out of the caller's territory (enforced in T008).

Concrete implementations (e.g. `coach.data_access.sqlite_store.SqliteStore`) live behind
this interface so swapping synthetic data for real connectors is a source change only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from coach.config.settings import scope_level_for
from coach.schemas import (
    Account,
    AccountBrandMetrics,
    BusinessMetric,
    CallActivity,
    CloseRecord,
    CoachingSession,
    Rep,
    Role,
    ScopeLevel,
)


class ScopeError(Exception):
    """Raised when a caller requests data outside their territory scope (RBAC, T008)."""


@dataclass(frozen=True)
class AccessContext:
    """The caller's identity and territory scope.

    Access is scoped by `scope_level`, derived from the role via the single config source
    (`config.ROLE_SCOPE_LEVELS`) when not supplied. All non-rep roles have FULL access
    within their scope (no read-only).
    """

    user_id: str
    role: Role
    region_id: str
    district_id: str | None = None  # set for a district-level caller (a DM)
    rep_id: str | None = None  # set for a self-scope caller (a rep)
    scope_level: ScopeLevel | None = None  # derived from role (config) if not given

    def __post_init__(self) -> None:
        if self.scope_level is None:
            object.__setattr__(self, "scope_level", scope_level_for(self.role))


@runtime_checkable
class DataAccess(Protocol):
    """Structured reads. All reads take an `AccessContext`."""

    def get_reps(self, ctx: AccessContext) -> list[Rep]: ...

    def get_rep(self, ctx: AccessContext, rep_id: str) -> Rep: ...

    def get_accounts(self, ctx: AccessContext, rep_id: str) -> list[Account]: ...

    def get_account_brand_metrics(
        self, ctx: AccessContext, rep_id: str
    ) -> list[AccountBrandMetrics]: ...

    def get_call_activity(self, ctx: AccessContext, rep_id: str) -> list[CallActivity]: ...

    def get_business_metrics(self, ctx: AccessContext, rep_id: str) -> list[BusinessMetric]: ...

    def get_coaching_sessions(self, ctx: AccessContext, rep_id: str) -> list[CoachingSession]: ...

    # The single WRITE path (Phase 10 / capability #2): record a CLOSE note. Enforces the SAME
    # RBAC as reads — the writer may only write for a rep in their own scope (out-of-scope ->
    # ScopeError). The note is persisted so the existing scoped + PRP-scrubbed readback surfaces
    # it later (ADR 0002). It RECORDS the human's input — never an autonomous action (FR-011).
    def save_close_record(self, ctx: AccessContext, record: CloseRecord) -> CloseRecord: ...


@runtime_checkable
class Retriever(Protocol):
    """Coaching-notes RAG. Implemented in a later phase (embeddings + vector store)."""

    def search_notes(
        self, ctx: AccessContext, rep_id: str, query: str, k: int = 4
    ) -> list[CoachingSession]: ...
