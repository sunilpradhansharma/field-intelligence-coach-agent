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
    follow_up_done INTEGER NOT NULL
);
"""


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
            "INSERT INTO coaching_sessions VALUES (?,?,?,?,?,?,?)",
            [
                (
                    s.session_id,
                    s.rep_id,
                    s.date,
                    s.notes_text,
                    json.dumps(s.agreed_actions),
                    json.dumps(s.observe_next),
                    int(s.follow_up_done),
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
            )
            for r in rows
        ]

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
