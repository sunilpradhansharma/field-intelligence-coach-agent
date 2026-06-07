"""Local SQLite implementation of the `DataAccess` interface (MVP structured store).

Maps to Aurora Postgres / Athena+S3 in production — same interface, swapped impl.

NOTE (scope): RBAC *enforcement* (out-of-scope denial via `ScopeError`, RBD read-only
rules, and the dedicated RBAC tests) is task T008 and is intentionally NOT implemented
in the foundation phase. The reads below load the caller's territory partition (a DM's
district, or all districts in an RBD's region); they do not yet deny out-of-scope
single-id reads. The TODO markers point to where T008 will add enforcement.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from coach.data_access.interface import AccessContext, DataAccess
from coach.schemas import (
    Account,
    AccountType,
    BusinessMetric,
    CallActivity,
    CoachingSession,
    Dataset,
    OpportunityLevel,
    Performance,
    Rep,
    Role,
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
    risk_flag INTEGER NOT NULL
);
CREATE TABLE call_activity (
    activity_id TEXT PRIMARY KEY, rep_id TEXT NOT NULL, account_id TEXT NOT NULL,
    period TEXT NOT NULL, calls INTEGER NOT NULL, calls_trend REAL NOT NULL
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
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row

    # ----------------------------------------------------------------- lifecycle
    def __enter__(self) -> SqliteStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------- writes
    def init_schema(self) -> None:
        """(Re)create the empty schema."""
        cur = self._conn.cursor()
        for table in (
            "coaching_sessions",
            "call_activity",
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
            "INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
                )
                for a in ds.accounts
            ],
        )
        cur.executemany(
            "INSERT INTO call_activity VALUES (?,?,?,?,?,?)",
            [
                (c.activity_id, c.rep_id, c.account_id, c.period, c.calls, c.calls_trend)
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

    # -------------------------------------------------------------------- reads
    def _allowed_district_ids(self, ctx: AccessContext) -> list[str]:
        """Districts the caller may read. (RBAC enforcement hardening is T008.)"""
        if ctx.role == Role.district_manager and ctx.district_id is not None:
            return [ctx.district_id]
        # RBD: all districts in the region.
        rows = self._conn.execute(
            "SELECT district_id FROM districts WHERE region_id = ?", (ctx.region_id,)
        ).fetchall()
        return [r["district_id"] for r in rows]

    def get_reps(self, ctx: AccessContext) -> list[Rep]:
        placeholders = ",".join("?" for _ in self._allowed_district_ids(ctx))
        ids = self._allowed_district_ids(ctx)
        rows = self._conn.execute(
            f"SELECT * FROM reps WHERE district_id IN ({placeholders}) ORDER BY rep_id", ids
        ).fetchall()
        return [_rep(r) for r in rows]

    def get_rep(self, ctx: AccessContext, rep_id: str) -> Rep:
        row = self._conn.execute("SELECT * FROM reps WHERE rep_id = ?", (rep_id,)).fetchone()
        if row is None:
            raise KeyError(rep_id)
        # TODO(T008): raise ScopeError if row['district_id'] not in allowed districts.
        return _rep(row)

    def get_accounts(self, ctx: AccessContext, rep_id: str) -> list[Account]:
        rows = self._conn.execute(
            "SELECT * FROM accounts WHERE rep_id = ? ORDER BY account_id", (rep_id,)
        ).fetchall()
        return [_account(r) for r in rows]

    def get_call_activity(self, ctx: AccessContext, rep_id: str) -> list[CallActivity]:
        rows = self._conn.execute(
            "SELECT * FROM call_activity WHERE rep_id = ? ORDER BY activity_id", (rep_id,)
        ).fetchall()
        return [
            CallActivity(
                activity_id=r["activity_id"],
                rep_id=r["rep_id"],
                account_id=r["account_id"],
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

    def get_coaching_sessions(self, ctx: AccessContext, rep_id: str) -> list[CoachingSession]:
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
    )
