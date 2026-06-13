"""Step 5b — the read-only FastAPI surface (T016 / T025 / T037).

Covers (offline, with fake LLM + embeddings, a per-request connection to a seeded temp DB):
- the read-only surface (replaces the superseded F6): ONLY GET routes exist;
- RBAC via the API (replaces the superseded F8): a DM sees only their district; region sees the
  region; "all" sees everything; an out-of-scope rep_id -> 403 indistinguishable from not-found;
  the caller cannot override their scope;
- PRP via the API: PRP HCPs never appear in any brief, at every scope level;
- narrate-before-expose: no response body carries a PENDING_* placeholder (and an un-narrated
  path is a 500, never a leaked placeholder);
- per-request DB connection: each request opens and closes its own store connection.
"""

import pytest
from fastapi.testclient import TestClient

from coach.api.app import AppDeps, create_app
from coach.config.settings import get_settings
from coach.data_access.sqlite_store import SqliteStore
from coach.llm.embeddings import FakeEmbeddings
from coach.orchestrator.assembly import PENDING_PLACEHOLDERS
from coach.synthetic import generate

SEED = 42
DM = {"X-User-Id": "dm_d1"}
DM2 = {"X-User-Id": "dm_d2"}
REGION = {"X-User-Id": "region_r1"}
HOS = {"X-User-Id": "hos_1"}


class FakeLLM:
    """Deterministic narrator — fixed non-empty wording for every section (no live Bedrock)."""

    def narrate(self, reason_input: dict, instruction: str) -> str:
        return "Narrated wording for this section."


class EmptyLLM:
    """Returns empty wording — leaves every placeholder in place (the failure mode)."""

    def narrate(self, reason_input: dict, instruction: str) -> str:
        return ""


@pytest.fixture
def db_path(tmp_path):
    """A seeded, file-backed DB so per-request connections share data (maps to Aurora)."""
    p = tmp_path / "coach.db"
    store = SqliteStore(str(p))
    store.write_dataset(generate(SEED))
    store.close()
    return str(p)


def _deps(db_path, llm=None, embedder=None, store_factory=None):
    kwargs = dict(
        db_path=db_path,
        settings=get_settings(),
        llm=llm or FakeLLM(),
        embedder=embedder or FakeEmbeddings(),
    )
    if store_factory is not None:
        kwargs["store_factory"] = store_factory
    return AppDeps(**kwargs)


@pytest.fixture
def client(db_path):
    app = create_app(_deps(db_path))
    return TestClient(app, raise_server_exceptions=False)


# --------------------------------------------------------------- read-only surface (F6 replaced)
def test_only_reads_and_the_close_capture_write_are_exposed(client):
    """The surface is read-only EXCEPT the one CLOSE-capture write, which RECORDS the DM's own
    observations (not an autonomous action — FR-011). The only non-GET route allowed is
    `POST /api/brief/{rep_id}/close`; nothing else may expose a write/action verb."""
    for route in client.app.routes:
        verbs = (getattr(route, "methods", None) or set()) - {"HEAD", "OPTIONS"}
        path = getattr(route, "path", "")
        if path == "/api/brief/{rep_id}/close":
            assert verbs == {"POST"}, f"{path} should be POST-only, got {verbs}"
        else:
            assert verbs <= {"GET"}, f"{path} exposes non-GET {verbs}"


# ----------------------------------------------------------------------------- whoami / identity
def test_whoami_resolves_dm_scope_from_role(client):
    r = client.get("/api/whoami", headers=DM)
    assert r.status_code == 200
    assert r.json() == {
        "user_id": "dm_d1",
        "role": "district_manager",
        "scope_level": "district",
        "district_id": "D1",
        "region_id": "R1",
    }


def test_whoami_region_and_all_scopes(client):
    assert client.get("/api/whoami", headers=REGION).json()["scope_level"] == "region"
    assert client.get("/api/whoami", headers=HOS).json()["scope_level"] == "all"


def test_missing_identity_is_401(client):
    assert client.get("/api/whoami").status_code == 401


def test_unknown_identity_is_401(client):
    assert client.get("/api/whoami", headers={"X-User-Id": "nobody"}).status_code == 401


# ----------------------------------------------------------------------- RBAC via API (F8 replaced)
def test_dm_reps_are_scoped_to_their_district(client):
    body = client.get("/api/reps", headers=DM).json()
    assert body["synthetic"] is True
    assert body["scope"]["scope_level"] == "district"
    rep_ids = [r["rep_id"] for r in body["ranked_reps"]]
    assert rep_ids and all(rid.startswith("rep_d1_") for rid in rep_ids)


def test_region_sees_both_districts(client):
    # A region caller's full ranking spans both districts (limit high enough to include both).
    rep_ids = [
        r["rep_id"] for r in client.get("/api/reps?limit=50", headers=REGION).json()["ranked_reps"]
    ]
    assert any(rid.startswith("rep_d1_") for rid in rep_ids)
    assert any(rid.startswith("rep_d2_") for rid in rep_ids)


def test_head_of_sales_sees_all(client):
    rep_ids = [
        r["rep_id"] for r in client.get("/api/reps?limit=50", headers=HOS).json()["ranked_reps"]
    ]
    assert any(rid.startswith("rep_d1_") for rid in rep_ids)
    assert any(rid.startswith("rep_d2_") for rid in rep_ids)


def test_dm_can_get_an_in_scope_brief(client):
    r = client.get("/api/brief/rep_d1_001", headers=DM)
    assert r.status_code == 200
    body = r.json()
    assert body["selected_rep_id"] == "rep_d1_001"
    assert body["synthetic"] is True
    assert body["generated_for"]["scope_level"] == "district"


def test_out_of_scope_rep_is_403_indistinguishable_from_not_found(client):
    # A DM asking for another district's rep, and for a rep that does not exist, get the SAME 403
    # with the SAME body — existence is never leaked (FR-014).
    out_of_scope = client.get("/api/brief/rep_d2_001", headers=DM)
    not_found = client.get("/api/brief/rep_d1_999", headers=DM)
    assert out_of_scope.status_code == 403
    assert not_found.status_code == 403
    assert out_of_scope.json() == not_found.json() == {"detail": "forbidden"}


def test_caller_cannot_widen_scope_via_input(client):
    # There is no scope/territory input; a DM stays district-scoped no matter what they pass.
    assert client.get("/api/whoami?scope_level=all", headers=DM).json()["scope_level"] == "district"
    assert client.get("/api/brief/rep_d2_001", headers=DM).status_code == 403


# ------------------------------------------------------------------------------ PRP via the API
def test_prp_accounts_never_appear_in_a_brief(client):
    ds = generate(SEED)
    prp_ids = {a.account_id for a in ds.accounts if a.prp}
    assert prp_ids  # guard: the seed contains PRP HCPs
    # A DM brief and a head-of-sales (scope "all") brief — neither may surface a PRP account.
    for headers, rep in ((DM, "rep_d1_001"), (HOS, "rep_d2_001")):
        body = client.get(f"/api/brief/{rep}", headers=headers).json()
        acct_ids = {a["account_id"] for a in body["accounts"]}
        assert prp_ids.isdisjoint(acct_ids)


# ----------------------------------------------------------------------- narrate before expose
def test_no_placeholder_in_a_brief_response(client):
    text = client.get("/api/brief/rep_d1_001", headers=DM).text
    for placeholder in PENDING_PLACEHOLDERS:
        assert placeholder not in text


def test_no_placeholder_in_a_reps_response(client):
    text = client.get("/api/reps", headers=DM).text
    for placeholder in PENDING_PLACEHOLDERS:
        assert placeholder not in text


def test_un_narrated_path_is_never_exposed(db_path):
    # An LLM that narrates nothing leaves placeholders -> the guard makes it a 500, and the
    # error body carries NO placeholder (no un-narrated content reaches the client).
    client = TestClient(create_app(_deps(db_path, llm=EmptyLLM())), raise_server_exceptions=False)
    for path in ("/api/brief/rep_d1_001", "/api/reps"):
        r = client.get(path, headers=DM)
        assert r.status_code == 500
        assert r.json() == {"detail": "internal error"}
        for placeholder in PENDING_PLACEHOLDERS:
            assert placeholder not in r.text


# --------------------------------------------------------------------- per-request connection
def test_each_request_opens_and_closes_its_own_connection(db_path):
    opened: list[SqliteStore] = []
    closed: list[SqliteStore] = []

    def counting_factory(path: str) -> SqliteStore:
        store = SqliteStore(path)
        opened.append(store)
        original_close = store.close

        def tracked_close() -> None:
            closed.append(store)
            original_close()

        store.close = tracked_close  # type: ignore[method-assign]
        return store

    client = TestClient(
        create_app(_deps(db_path, store_factory=counting_factory)),
        raise_server_exceptions=False,
    )
    assert client.get("/api/whoami", headers=DM).status_code == 200
    assert client.get("/api/reps", headers=DM).status_code == 200
    assert client.get("/api/brief/rep_d1_001", headers=DM).status_code == 200

    # One fresh connection per request (3 requests), each closed — no process-wide sharing.
    assert len(opened) == 3
    assert len(closed) == 3
    assert all(store in closed for store in opened)


def test_sequential_requests_are_independent(client):
    # No shared per-request state leaks between callers: a region read then a DM read each stay
    # correctly scoped.
    region_ids = [
        r["rep_id"] for r in client.get("/api/reps?limit=50", headers=REGION).json()["ranked_reps"]
    ]
    dm_ids = [r["rep_id"] for r in client.get("/api/reps", headers=DM).json()["ranked_reps"]]
    assert any(rid.startswith("rep_d2_") for rid in region_ids)
    assert all(rid.startswith("rep_d1_") for rid in dm_ids)


# ----------------------------- regression: appended coaching_sessions.account_id read by NAME
def test_ranking_server_path_reads_coaching_sessions_account_id_by_name(db_path):
    """Regression for the Phase 10 appended `account_id` column on `coaching_sessions`.

    The server ranking path (`/api/reps` -> `rank_reps` -> `compute_rep_signals` ->
    `get_coaching_sessions`) reads coaching-session rows over the REAL file-backed connection and
    its `sqlite3.Row` factory. Because every column is read BY NAME, appending `account_id` as the
    last column can never raise `IndexError: No item with that key`. The in-memory unit tests build
    `CoachingSession`/`CloseRecord` objects directly and never exercise this row-factory read of a
    persisted row carrying `account_id` — this test does, on the same path the API uses."""
    from coach.data_access.interface import AccessContext
    from coach.schemas import CloseRecord, Role

    dm = AccessContext(
        user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
    )
    store = SqliteStore(db_path)
    try:
        # Tie a CLOSE note to a real, NON-PRP account for an in-scope rep -> a non-null account_id.
        account_id = store.get_accounts(dm, "rep_d1_001")[0].account_id
        store.save_close_record(
            dm,
            CloseRecord(
                rep_id="rep_d1_001",
                date="2026-06-09",
                observations="Strong open.",
                agreed_actions=["Roleplay objections"],
                observe_next=[],
                account_id=account_id,
            ),
        )
        # get_coaching_sessions returns account_id, read BY NAME — the persisted non-null value
        # round-trips, and the column is Optional (a seeded note may legitimately carry None).
        sessions = store.get_coaching_sessions(dm, "rep_d1_001")
        assert any(s.account_id == account_id for s in sessions)
        assert all(s.account_id is None or isinstance(s.account_id, str) for s in sessions)
    finally:
        store.close()

    # The SERVER path that the runtime IndexError broke: ranking reads coaching_sessions for every
    # in-scope rep. A row-access bug would surface as a 500 here; a clean read is a 200.
    client = TestClient(create_app(_deps(db_path)), raise_server_exceptions=False)
    r = client.get("/api/reps", headers=DM)
    assert r.status_code == 200
    assert r.json()["ranked_reps"]  # the ranking (which read coaching_sessions) was produced
