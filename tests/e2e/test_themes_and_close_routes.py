"""Phase 7 + Phase 10 over the API (backend only — no UI).

GET /api/themes — the leadership theme aggregation: a region/all caller gets 200 with themes
(patterns/counts ONLY — NO rep id or name in the body); a DM gets the SAME 403 the app returns
everywhere (indistinguishable from not-found). POST /api/brief/{rep_id}/close — the CLOSE capture:
a DM may record a note for an in-scope rep (200 + saved record) through the EXISTING single door
(writer-scope RBAC); an out-of-scope rep -> 403; the saved note then flows back through the scoped
+ PRP-scrubbed ride-along readback (the loop closes), and a PRP-tied note is scrubbed on readback.

All offline (FakeLLM + FakeEmbeddings, no Bedrock) and also verified with the factory's offline
default (no BEDROCK_MODEL_ID).
"""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from coach.api.app import AppDeps, create_app
from coach.config.settings import get_settings
from coach.data_access.sqlite_store import SqliteStore
from coach.llm.embeddings import FakeEmbeddings
from coach.llm.factory import make_embedder, make_llm
from coach.synthetic import generate

SEED = 42
DM = {"X-User-Id": "dm_d1"}
DM2 = {"X-User-Id": "dm_d2"}
REGION = {"X-User-Id": "region_r1"}
HOS = {"X-User-Id": "hos_1"}


class FakeLLM:
    def narrate(self, reason_input: dict, instruction: str) -> str:
        return "Narrated wording for this section."


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "coach.db"
    store = SqliteStore(str(p))
    store.write_dataset(generate(SEED))
    store.close()
    return str(p)


def _deps(db_path, llm=None, embedder=None):
    return AppDeps(
        db_path=db_path,
        settings=get_settings(),
        llm=llm or FakeLLM(),
        embedder=embedder or FakeEmbeddings(),
    )


@pytest.fixture
def client(db_path):
    return TestClient(create_app(_deps(db_path)), raise_server_exceptions=False)


def _rep_ids(ds):
    return {r.rep_id for r in ds.reps}


def _non_prp_account(ds, rep_id):
    return next(a.account_id for a in ds.accounts if a.rep_id == rep_id and not a.prp)


# ===================================================================== GET /api/themes
def test_region_gets_themes_200_with_no_rep_identity_in_body(client):
    r = client.get("/api/themes", headers=REGION)
    assert r.status_code == 200
    body = r.json()
    assert body["themes"], "expected at least one aggregated theme"
    # patterns/counts only: each theme carries a label + counts/shares, never a rep field
    for t in body["themes"]:
        assert "theme" in t
        assert "rep_id" not in t and "name" not in t
    # airtight: NO rep id appears ANYWHERE in the serialized body (structural privacy, FR-016)
    ds = generate(SEED)
    blob = r.text
    for rid in _rep_ids(ds):
        assert rid not in blob, f"rep id {rid} leaked into the themes response"
    for rep in ds.reps:
        assert rep.name not in blob, f"rep name {rep.name!r} leaked into the themes response"


def test_all_scope_gets_themes_200(client):
    r = client.get("/api/themes", headers=HOS)
    assert r.status_code == 200
    assert r.json()["themes"]


def test_dm_gets_403_for_themes_indistinguishable_from_not_found(client):
    # A DM (district scope) may not aggregate — same clean 403 the app returns for out-of-scope.
    r = client.get("/api/themes", headers=DM)
    assert r.status_code == 403
    assert r.json() == {"detail": "forbidden"}


def test_themes_requires_identity(client):
    assert client.get("/api/themes").status_code == 401


# ============================================================ POST /api/brief/{rep_id}/close
def test_dm_saves_close_for_in_scope_rep_200(client):
    body = {
        "observations": "Strong opening; agreed to roleplay objections.",
        "agreed_actions": ["Roleplay objection handling"],
        "observe_next": ["Confirm pre-call plans"],
    }
    r = client.post("/api/brief/rep_d1_001/close", headers=DM, json=body)
    assert r.status_code == 200
    saved = r.json()["saved"]
    assert saved["rep_id"] == "rep_d1_001"
    assert saved["author_user_id"] == "dm_d1"  # author stamped from the context, not the body
    assert saved["observations"] == body["observations"]
    assert saved["session_id"]


def test_close_transcript_path_keeps_observations_verbatim(client):
    # The typed/spoken path: observations are the DM's verbatim transcript (never LLM-altered).
    transcript = "We worked the top account; the rep will pre-plan the next three calls."
    r = client.post("/api/brief/rep_d1_001/close", headers=DM, json={"transcript": transcript})
    assert r.status_code == 200
    assert r.json()["saved"]["observations"] == transcript


def test_close_out_of_scope_rep_is_403(client):
    # A D1 DM cannot write for a D2 rep, nor for a non-existent rep — both the same 403.
    assert (
        client.post(
            "/api/brief/rep_d2_001/close", headers=DM, json={"observations": "x"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/brief/rep_d1_999/close", headers=DM, json={"observations": "x"}
        ).status_code
        == 403
    )


def test_empty_close_is_rejected_422(client):
    r = client.post("/api/brief/rep_d1_001/close", headers=DM, json={})
    assert r.status_code == 422


def test_loop_closes_saved_close_surfaces_in_the_brief(client):
    marker = "ZEBRA_MARKER_OBSERVATION"
    save = client.post(
        "/api/brief/rep_d1_001/close",
        headers=DM,
        json={"observations": f"Great ride. {marker}", "agreed_actions": ["Follow up Tuesday"]},
    )
    assert save.status_code == 200
    # The brief's ride-along read path surfaces the just-saved note (scoped + PRP-scrubbed).
    brief = client.get("/api/brief/rep_d1_001", headers=DM)
    assert brief.status_code == 200
    assert marker in brief.text


def test_close_tied_to_prp_account_is_scrubbed_on_readback(client, db_path):
    ds = generate(SEED)
    prp = next((a for a in ds.accounts if a.prp and a.rep_id.startswith("rep_d1")), None)
    if prp is None:
        pytest.skip("seed has no PRP account under D1")
    secret = "PRP_SECRET_MARKER"
    save = client.post(
        f"/api/brief/{prp.rep_id}/close",
        headers=DM,
        json={"observations": f"Note {secret}", "account_id": prp.account_id},
    )
    assert save.status_code == 200  # the write itself succeeds (DM owns the rep)
    # ...but the PRP-tied note must NEVER surface on readback, at any scope level.
    for headers in (DM, REGION, HOS):
        brief = client.get(f"/api/brief/{prp.rep_id}", headers=headers)
        if brief.status_code == 200:
            assert secret not in brief.text


# ====================================================== both routes work with NO Bedrock configured
def test_routes_work_offline_with_no_bedrock(db_path):
    s = replace(get_settings(), bedrock_model_id=None, bedrock_embed_model_id=None)
    deps = AppDeps(db_path=db_path, settings=s, llm=make_llm(s), embedder=make_embedder(s))
    client = TestClient(create_app(deps), raise_server_exceptions=False)
    assert client.get("/api/themes", headers=REGION).status_code == 200
    r = client.post("/api/brief/rep_d1_001/close", headers=DM, json={"transcript": "Good ride."})
    assert r.status_code == 200
    assert r.json()["saved"]["observations"] == "Good ride."
