"""Local SQLite implementation of the `DataAccess` interface (MVP structured store).

Maps to Aurora Postgres / Athena+S3 in production — same interface, swapped impl.

RBAC + PRP are enforced HERE, on every read (Principle V / FR-013, FR-020):
- **RBAC (T008)**: each read is scoped to the caller's `AccessContext.scope_level`
  (self / district / region / all). A read for an out-of-scope rep raises `ScopeError`.
- **PRP scrubbing (T008A)**: HCPs/accounts flagged ``prp = true`` (and their call activity)
  are dropped before results are returned, at every scope level — no PRP HCP reaches a
  field user. Scoping/scrubbing logic lives in `coach.data_access.rbac`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from coach.data_access import rbac
from coach.data_access.interface import AccessContext, DataAccess
from coach.schemas import (
    Account,
    AccountBrandMetrics,
    AccountType,
    Brand,
    BusinessMetric,
    CallActivity,
    CloseRecord,
    CoachingSession,
    Dataset,
    OpportunityLevel,
    Performance,
    Rep,
    Role,
    User,
)

_SCHEMA = """
CREATE TABLE regions (region_id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE districts (
    district_id TEXT PRIMARY KEY, region_id TEXT NOT NULL, name TEXT NOT NULL
);
CREATE TABLE users (
    user_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
    region_id TEXT NOT NULL, district_id TEXT
);
CREATE TABLE reps (
    rep_id TEXT PRIMARY KEY, name TEXT NOT NULL, district_id TEXT NOT NULL,
    tenure_months INTEGER NOT NULL
);
CREATE TABLE accounts (
    account_id TEXT PRIMARY KEY, rep_id TEXT NOT NULL, name TEXT NOT NULL, type TEXT NOT NULL,
    market_share REAL NOT NULL, share_trend REAL NOT NULL, volume REAL NOT NULL,
    spend REAL NOT NULL, performance TEXT NOT NULL, opportunity_level TEXT NOT NULL,
    risk_flag INTEGER NOT NULL, prp INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE account_brand_metrics (
    account_id TEXT NOT NULL, brand TEXT NOT NULL,
    market_share REAL NOT NULL, share_trend REAL NOT NULL, volume REAL NOT NULL,
    spend REAL NOT NULL, performance TEXT NOT NULL, opportunity_level TEXT NOT NULL,
    risk_flag INTEGER NOT NULL,
    PRIMARY KEY (account_id, brand)
);
CREATE TABLE call_activity (
    activity_id TEXT PRIMARY KEY, rep_id TEXT NOT NULL, account_id TEXT NOT NULL,
    brand TEXT NOT NULL, period TEXT NOT NULL, calls INTEGER NOT NULL, calls_trend REAL NOT NULL
);
CREATE TABLE coaching_sessions (
    session_id TEXT PRIMARY KEY, rep_id TEXT NOT NULL, date TEXT NOT NULL,
    notes_text TEXT NOT NULL, agreed_actions TEXT NOT NULL, observe_next TEXT NOT NULL,
    follow_up_done INTEGER NOT NULL, account_id TEXT
);
"""

# Schema version stamped into every generated DB (SQLite `PRAGMA user_version`). BUMP this whenever
# the table definitions in `_SCHEMA` change, so an old on-disk DB is DETECTED and the user is told
# to regenerate — synthetic-only, we do NOT migrate. History: v1 = the original schema; v2 added
# `coaching_sessions.account_id` and the per-(account, brand) `account_brand_metrics` columns.
# (A DB built before versioning existed has the SQLite default `user_version = 0`, so it also
# fails the check and is reported as stale.)
SCHEMA_VERSION = 2


class SchemaVersionError(RuntimeError):
    """Raised when an on-disk DB's stamped schema version does not match the code's
    `SCHEMA_VERSION` — the DB predates the current schema and must be regenerated."""


def schema_mismatch_message(path: str, found: int, expected: int) -> str:
    """The CLEAR, actionable message for a stale DB (preferred over a cryptic downstream error)."""
    return (
        f"Database at {path} was built with schema v{found} but the code expects v{expected}. "
        f"Regenerate it: uv run python -m coach.synthetic.generate --seed 42"
    )


class SqliteStore(DataAccess):
    """SQLite-backed structured store. Use as a context manager or call `close()`."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conns: list[sqlite3.Connection] = []  # every open connection (for close())
        self._local = threading.local()  # one connection PER THREAD (a small pool)
        if db_path == ":memory:":
            # A uniquely-named, shared-cache in-memory DB: each thread opens its OWN connection
            # that still sees the same data (a bare ":memory:" DB is private to one connection).
            self._target = f"file:coach-mem-{id(self):x}?mode=memory&cache=shared"
            self._use_uri = True
        else:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self._target = db_path
            self._use_uri = False
        # The orchestrator runs the independent section reads on PARALLEL worker threads. A
        # single shared sqlite connection is not safe for that; instead each thread gets its
        # OWN connection (the `_conn` property below), so reads never race. This is the small
        # connection pool the data-access boundary needs — it maps to a connection pool /
        # Aurora in production. The keeper conn (the owning thread's) also keeps a shared-cache
        # in-memory DB alive for the store's lifetime.
        self._keeper = self._new_connection()

    # ----------------------------------------------------------------- lifecycle
    def __enter__(self) -> SqliteStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _new_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._target, uri=self._use_uri)
        conn.row_factory = sqlite3.Row
        with self._lock:
            self._conns.append(conn)
        self._local.conn = conn
        return conn

    @property
    def _conn(self) -> sqlite3.Connection:
        """The CURRENT thread's connection (opened lazily). Per-thread connections make the
        orchestrator's parallel section reads safe without a process-wide shared connection."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._new_connection()
        return conn

    def close(self) -> None:
        with self._lock:
            conns = list(self._conns)
            self._conns.clear()
        for conn in conns:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    # ------------------------------------------------------------------- writes
    def init_schema(self) -> None:
        """(Re)create the empty schema."""
        cur = self._conn.cursor()
        for table in (
            "coaching_sessions",
            "call_activity",
            "account_brand_metrics",
            "accounts",
            "reps",
            "users",
            "districts",
            "regions",
        ):
            cur.execute(f"DROP TABLE IF EXISTS {table}")
        cur.executescript(_SCHEMA)
        # Stamp the schema version so a later open can detect a stale DB (PRAGMA takes no bound
        # params; SCHEMA_VERSION is our own int constant, so the f-string is safe).
        cur.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")
        self._conn.commit()

    def write_dataset(self, ds: Dataset) -> None:
        """Persist a synthetic dataset through the store (the data layer owns writes)."""
        self.init_schema()
        cur = self._conn.cursor()
        cur.executemany(
            "INSERT INTO regions VALUES (?,?)",
            [(r.region_id, r.name) for r in ds.regions],
        )
        cur.executemany(
            "INSERT INTO districts VALUES (?,?,?)",
            [(d.district_id, d.region_id, d.name) for d in ds.districts],
        )
        cur.executemany(
            "INSERT INTO users VALUES (?,?,?,?,?)",
            [(u.user_id, u.name, u.role.value, u.region_id, u.district_id) for u in ds.users],
        )
        cur.executemany(
            "INSERT INTO reps VALUES (?,?,?,?)",
            [(r.rep_id, r.name, r.district_id, r.tenure_months) for r in ds.reps],
        )
        cur.executemany(
            "INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    a.account_id,
                    a.rep_id,
                    a.name,
                    a.type.value,
                    a.market_share,
                    a.share_trend,
                    a.volume,
                    a.spend,
                    a.performance.value,
                    a.opportunity_level.value,
                    int(a.risk_flag),
                    int(a.prp),
                )
                for a in ds.accounts
            ],
        )
        cur.executemany(
            "INSERT INTO account_brand_metrics VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    m.account_id,
                    m.brand.value,
                    m.market_share,
                    m.share_trend,
                    m.volume,
                    m.spend,
                    m.performance.value,
                    m.opportunity_level.value,
                    int(m.risk_flag),
                )
                for m in ds.account_brand_metrics
            ],
        )
        cur.executemany(
            "INSERT INTO call_activity VALUES (?,?,?,?,?,?,?)",
            [
                (
                    c.activity_id,
                    c.rep_id,
                    c.account_id,
                    c.brand.value,
                    c.period,
                    c.calls,
                    c.calls_trend,
                )
                for c in ds.call_activity
            ],
        )
        cur.executemany(
            "INSERT INTO coaching_sessions VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    s.session_id,
                    s.rep_id,
                    s.date,
                    s.notes_text,
                    json.dumps(s.agreed_actions),
                    json.dumps(s.observe_next),
                    int(s.follow_up_done),
                    s.account_id,
                )
                for s in ds.coaching_sessions
            ],
        )
        self._conn.commit()

    # ---------------------------------------------------------------- identity
    def get_user(self, user_id: str) -> User | None:
        """Resolve a login identity to its `User` (role + territory).

        This is the PRE-AUTH identity lookup the API uses to BUILD an `AccessContext`; it is
        not territory data, so it is intentionally not RBAC-scoped. It exists here so the API
        never touches the raw connection (all reads go through the data-access layer). Returns
        `None` for an unknown id (the API maps that to `401`)."""
        row = self._conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        return User(
            user_id=row["user_id"],
            name=row["name"],
            role=Role(row["role"]),
            region_id=row["region_id"],
            district_id=row["district_id"],
        )

    # -------------------------------------------------------------------- reads
    # Every read enforces RBAC (scope level) and PRP scrubbing via `rbac` (T008/T008A).
    def get_reps(self, ctx: AccessContext) -> list[Rep]:
        rep_ids = rbac.scoped_rep_ids(self._conn, ctx)
        if not rep_ids:
            return []
        placeholders = ",".join("?" for _ in rep_ids)
        rows = self._conn.execute(
            f"SELECT * FROM reps WHERE rep_id IN ({placeholders}) ORDER BY rep_id", rep_ids
        ).fetchall()
        return [_rep(r) for r in rows]

    def get_rep(self, ctx: AccessContext, rep_id: str) -> Rep:
        # Scope check FIRST (FR-014): a rep that is out-of-scope OR non-existent both raise
        # ScopeError, so the caller cannot tell "exists elsewhere" from "does not exist".
        # `require_rep_in_scope` already treats an unknown rep as out-of-scope.
        rbac.require_rep_in_scope(self._conn, ctx, rep_id)
        row = self._conn.execute("SELECT * FROM reps WHERE rep_id = ?", (rep_id,)).fetchone()
        if row is None:
            raise KeyError(rep_id)  # only reachable for a self-caller's own missing rep_id
        return _rep(row)

    def get_accounts(self, ctx: AccessContext, rep_id: str) -> list[Account]:
        rbac.require_rep_in_scope(self._conn, ctx, rep_id)
        # PRP scrub (T008A): `prp = 0` drops restricted HCPs before they are returned.
        rows = self._conn.execute(
            "SELECT * FROM accounts WHERE rep_id = ? AND prp = 0 ORDER BY account_id", (rep_id,)
        ).fetchall()
        return [_account(r) for r in rows]

    def get_call_activity(self, ctx: AccessContext, rep_id: str) -> list[CallActivity]:
        rbac.require_rep_in_scope(self._conn, ctx, rep_id)
        # PRP scrub (T008A): exclude call activity tied to PRP-flagged accounts.
        rows = self._conn.execute(
            "SELECT * FROM call_activity WHERE rep_id = ? "
            "AND account_id NOT IN (SELECT account_id FROM accounts WHERE prp = 1) "
            "ORDER BY activity_id",
            (rep_id,),
        ).fetchall()
        return [
            CallActivity(
                activity_id=r["activity_id"],
                rep_id=r["rep_id"],
                account_id=r["account_id"],
                brand=Brand(r["brand"]),
                period=r["period"],
                calls=r["calls"],
                calls_trend=r["calls_trend"],
            )
            for r in rows
        ]

    def get_business_metrics(self, ctx: AccessContext, rep_id: str) -> list[BusinessMetric]:
        return [
            BusinessMetric(
                account_id=a.account_id,
                market_share=a.market_share,
                share_trend=a.share_trend,
                volume=a.volume,
                spend=a.spend,
                performance=a.performance,
            )
            for a in self.get_accounts(ctx, rep_id)
        ]

    def get_account_brand_metrics(
        self, ctx: AccessContext, rep_id: str
    ) -> list[AccountBrandMetrics]:
        # Per-(account, brand) metrics for a rep. RBAC-scoped + PRP-scrubbed (T008A/FR-020):
        # the join to `accounts` with `a.prp = 0` drops rows for restricted HCPs before they
        # are returned, so no PRP HCP leaks via account_brand_metrics. The Phase 4 accounts
        # component (FR-007) consumes this read; the deterministic scorer (T023) uses it too.
        rbac.require_rep_in_scope(self._conn, ctx, rep_id)
        rows = self._conn.execute(
            "SELECT abm.* FROM account_brand_metrics abm "
            "JOIN accounts a ON abm.account_id = a.account_id "
            "WHERE a.rep_id = ? AND a.prp = 0 "
            "ORDER BY abm.account_id, abm.brand",
            (rep_id,),
        ).fetchall()
        return [
            AccountBrandMetrics(
                account_id=r["account_id"],
                brand=Brand(r["brand"]),
                market_share=r["market_share"],
                share_trend=r["share_trend"],
                volume=r["volume"],
                spend=r["spend"],
                performance=Performance(r["performance"]),
                opportunity_level=OpportunityLevel(r["opportunity_level"]),
                risk_flag=bool(r["risk_flag"]),
            )
            for r in rows
        ]

    def get_coaching_sessions(self, ctx: AccessContext, rep_id: str) -> list[CoachingSession]:
        rbac.require_rep_in_scope(self._conn, ctx, rep_id)
        rows = self._conn.execute(
            "SELECT * FROM coaching_sessions WHERE rep_id = ? ORDER BY session_id", (rep_id,)
        ).fetchall()
        return [
            CoachingSession(
                session_id=r["session_id"],
                rep_id=r["rep_id"],
                date=r["date"],
                notes_text=r["notes_text"],
                agreed_actions=json.loads(r["agreed_actions"]),
                observe_next=json.loads(r["observe_next"]),
                follow_up_done=bool(r["follow_up_done"]),
                account_id=r["account_id"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------- write
    def save_close_record(self, ctx: AccessContext, record: CloseRecord) -> CloseRecord:
        """Record a CLOSE note through the single door (Phase 10 / capability #2).

        Writer-scope RBAC: `require_rep_in_scope` runs BEFORE any write, so a caller may write
        ONLY for a rep in their own scope — an out-of-scope (or non-existent) rep raises
        `ScopeError`, indistinguishable from not-found, exactly like a read. The author identity
        is stamped from the authenticated `ctx` (it cannot be spoofed). The note is persisted as a
        coaching note (carrying its `account_id`), so the existing scoped + PRP-scrubbed readback
        (ride-along prep / retriever) surfaces it next time — and a PRP-tied note is scrubbed there
        (ADR 0002). This RECORDS the DM's own input; it is not an autonomous action (FR-011)."""
        rbac.require_rep_in_scope(self._conn, ctx, record.rep_id)  # SAME RBAC as reads — fail first
        saved = record.model_copy(
            update={"author_user_id": ctx.user_id, "author_scope_level": ctx.scope_level}
        )
        # Persist as a coaching note in the SAME table the readback reads (no second path).
        self._conn.execute(
            "INSERT OR REPLACE INTO coaching_sessions VALUES (?,?,?,?,?,?,?,?)",
            (
                saved.session_id,
                saved.rep_id,
                saved.date,
                saved.observations,
                json.dumps(saved.agreed_actions),
                json.dumps(saved.observe_next),
                1,  # a recorded CLOSE note is a completed follow-up, not a missed one
                saved.account_id,
            ),
        )
        self._conn.commit()
        return saved

    # ------------------------------------------------------------- schema version
    def schema_version(self) -> int:
        """The schema version stamped in this DB (`PRAGMA user_version`); `0` if it was never
        stamped (an empty DB, or one built before schema versioning existed)."""
        return int(self._conn.execute("PRAGMA user_version").fetchone()[0])

    def has_schema(self) -> bool:
        """True if the core tables exist — distinguishes a populated DB from an empty/new file."""
        row = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'coaching_sessions'"
        ).fetchone()
        return row is not None

    def require_current_schema(self) -> None:
        """Raise `SchemaVersionError` (with a clear regenerate hint) if this DB's stamped schema
        version does not match the code's `SCHEMA_VERSION`. Prefer this loud, early failure over a
        cryptic downstream `IndexError` when a read hits a column an old DB does not have."""
        found = self.schema_version()
        if found != SCHEMA_VERSION:
            raise SchemaVersionError(schema_mismatch_message(self.db_path, found, SCHEMA_VERSION))

    # ---------------------------------------------------------------- test aid
    def count(self, table: str) -> int:
        """Row count for a table (used by foundation tests)."""
        if table not in {
            "regions",
            "districts",
            "users",
            "reps",
            "accounts",
            "account_brand_metrics",
            "call_activity",
            "coaching_sessions",
        }:
            raise ValueError(f"unknown table: {table}")
        return self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def _rep(r: sqlite3.Row) -> Rep:
    return Rep(
        rep_id=r["rep_id"],
        name=r["name"],
        district_id=r["district_id"],
        tenure_months=r["tenure_months"],
    )


def _account(r: sqlite3.Row) -> Account:
    return Account(
        account_id=r["account_id"],
        rep_id=r["rep_id"],
        name=r["name"],
        type=AccountType(r["type"]),
        market_share=r["market_share"],
        share_trend=r["share_trend"],
        volume=r["volume"],
        spend=r["spend"],
        performance=Performance(r["performance"]),
        opportunity_level=OpportunityLevel(r["opportunity_level"]),
        risk_flag=bool(r["risk_flag"]),
        prp=bool(r["prp"]),
    )
