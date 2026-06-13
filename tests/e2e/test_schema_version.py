"""PART A — stale-schema guard (prevents the "tests pass but the server crashes on an old DB"
class of bug).

The generator stamps the current `SCHEMA_VERSION` into every DB (`PRAGMA user_version`). When the
API opens a DB whose stamp differs (or is missing), it must fail with a CLEAR, actionable message
— "regenerate it: uv run python -m coach.synthetic.generate --seed 42" — instead of a cryptic
downstream `IndexError` when a read hits a column an old DB does not have. Synthetic-only: detect
and tell the user to regenerate; there are no migrations.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from coach.api.app import AppDeps, _verify_db_schema, create_app
from coach.config.settings import get_settings
from coach.data_access.sqlite_store import SCHEMA_VERSION, SchemaVersionError, SqliteStore
from coach.llm.embeddings import FakeEmbeddings
from coach.synthetic import generate

SEED = 42


class FakeLLM:
    def narrate(self, reason_input: dict, instruction: str) -> str:
        return "Narrated."


def _seeded_db(tmp_path) -> str:
    p = tmp_path / "coach.db"
    store = SqliteStore(str(p))
    store.write_dataset(generate(SEED))
    store.close()
    return str(p)


def _stamp(db_path: str, version: int) -> None:
    """Force a DB's stamped schema version (simulates a DB built by older code)."""
    conn = sqlite3.connect(db_path)
    conn.execute(f"PRAGMA user_version = {int(version)}")
    conn.commit()
    conn.close()


def _deps(db_path: str) -> AppDeps:
    return AppDeps(
        db_path=db_path, settings=get_settings(), llm=FakeLLM(), embedder=FakeEmbeddings()
    )


# ------------------------------------------------- the generator stamps the current version
def test_generated_db_is_stamped_with_current_version(tmp_path):
    store = SqliteStore(_seeded_db(tmp_path))
    try:
        assert store.schema_version() == SCHEMA_VERSION
        assert store.has_schema()
        store.require_current_schema()  # current -> no raise
    finally:
        store.close()


# --------------------------------------------- an old stamp is detected with a clear message
def test_old_schema_version_raises_clear_actionable_error(tmp_path):
    db = _seeded_db(tmp_path)
    _stamp(db, SCHEMA_VERSION - 1)  # a DB built by older code
    store = SqliteStore(db)
    try:
        with pytest.raises(SchemaVersionError) as ei:
            store.require_current_schema()
    finally:
        store.close()
    msg = str(ei.value)
    assert f"schema v{SCHEMA_VERSION - 1}" in msg
    assert f"expects v{SCHEMA_VERSION}" in msg
    assert db in msg
    assert "uv run python -m coach.synthetic.generate --seed 42" in msg


# ------------------------------------- a missing stamp (pre-versioning DB, user_version 0) too
def test_unstamped_db_is_treated_as_a_mismatch(tmp_path):
    db = _seeded_db(tmp_path)
    _stamp(db, 0)  # the SQLite default — a DB built before versioning existed
    store = SqliteStore(db)
    try:
        with pytest.raises(SchemaVersionError):
            store.require_current_schema()
    finally:
        store.close()


# --------------------------------------------------------------- app startup: current DB ok
def test_app_startup_passes_on_a_current_db(tmp_path):
    db = _seeded_db(tmp_path)
    # Entering the TestClient context runs the lifespan startup guard.
    with TestClient(create_app(_deps(db))) as client:
        assert client.get("/api/whoami", headers={"X-User-Id": "dm_d1"}).status_code == 200


# ------------------------------------------------------ app startup: stale DB fails loudly
def test_app_startup_fails_loudly_on_a_stale_db(tmp_path):
    db = _seeded_db(tmp_path)
    _stamp(db, SCHEMA_VERSION - 1)
    with pytest.raises(SchemaVersionError):
        with TestClient(create_app(_deps(db))):  # lifespan startup raises before serving
            pass


# ----------------------- the guard skips an in-memory / absent DB (nothing persisted to stale)
def test_verify_skips_in_memory_and_absent_db(tmp_path):
    _verify_db_schema(_deps(":memory:"))  # no raise — nothing on disk
    _verify_db_schema(_deps(str(tmp_path / "does-not-exist.db")))  # absent file -> no raise
