"""T039 — the minimal read-only web UI.

The page itself is static HTML/JS, so these tests verify the contract it relies on rather than
the DOM: the page is served (GET), it is read-only (no write/mutation route, and the page
references only GET endpoints), and the brief the page renders carries a visible `reason` for
EVERY section (the FR-010 promise the UI exists to display). The brief is fetched through the
API with the offline fake LLM/embeddings — no live Bedrock call.
"""

import re

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


@pytest.fixture
def client(db_path):
    deps = AppDeps(
        db_path=db_path, settings=get_settings(), llm=FakeLLM(), embedder=FakeEmbeddings()
    )
    return TestClient(create_app(deps), raise_server_exceptions=False)


# ------------------------------------------------------------------------- the page is served
def test_index_page_is_served_as_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert "Morning" in body and "Coaching" in body  # the masthead title
    # the seeded-user selector the demo uses
    for uid in ("dm_d1", "dm_d2", "region_r1", "hos_1"):
        assert uid in body


def test_page_is_read_only_and_calls_only_get_endpoints(client):
    body = client.get("/").text
    # It references the three GET endpoints...
    assert "/api/whoami" in body
    assert "/api/reps" in body
    assert "/api/brief/" in body
    # ...and never issues a mutating fetch (no write verb anywhere in the page script).
    assert not re.search(r"""method\s*:\s*['"](POST|PUT|PATCH|DELETE)['"]""", body, re.I)


def test_ui_layer_exposes_no_write_route(client):
    # The whole app surface (page + API) stays GET-only — the UI adds no mutation route.
    for route in client.app.routes:
        verbs = (getattr(route, "methods", None) or set()) - {"HEAD", "OPTIONS"}
        assert verbs <= {"GET"}, f"{getattr(route, 'path', route)} exposes non-GET {verbs}"


# ------------------------------------------------- FR-010: a reason for EVERY brief section
def _has_reason(obj) -> bool:
    return bool(obj.get("reason") and obj["reason"].get("summary", "").strip())


def _no_placeholder(summary: str) -> bool:
    return summary not in PENDING_PLACEHOLDERS


def test_rendered_brief_shows_a_reason_for_every_section(client):
    """The data the page renders carries a visible, non-placeholder reason on every
    recommendation across all five sections — the core FR-010 promise."""
    brief = client.get("/api/brief/rep_d1_001", headers=DM).json()

    # 1: ranked reps (the selected rep's priority) — each carries a reason
    assert brief["ranked_reps"]
    for rep in brief["ranked_reps"]:
        assert _has_reason(rep) and _no_placeholder(rep["reason"]["summary"])

    # 2: coaching focus
    assert brief["coaching_focus"]
    for f in brief["coaching_focus"]:
        assert _has_reason(f) and _no_placeholder(f["reason"]["summary"])

    # 3: ride-along prep (RideAlongPrep or EmptyState — both carry a reason)
    assert _has_reason(brief["ride_along_prep"])

    # 4: accounts (each per-(account, brand) focus carries a reason)
    for a in brief["accounts"]:
        assert _has_reason(a) and _no_placeholder(a["reason"]["summary"])

    # 5: opener
    assert _has_reason(brief["opener"]) and _no_placeholder(brief["opener"]["reason"]["summary"])


def test_no_history_rep_renders_a_clean_empty_state(client):
    """The FR-018 edge case the page must show as a clean message, not a blank/error."""
    ds = generate(SEED)
    with_history = {s.rep_id for s in ds.coaching_sessions}
    no_history = next(
        r.rep_id for r in ds.reps if r.district_id == "D1" and r.rep_id not in with_history
    )
    ra = client.get(f"/api/brief/{no_history}", headers=DM).json()["ride_along_prep"]
    assert ra["has_history"] is False
    assert ra["message"].strip()  # a real "no prior history" message to display
    assert _has_reason(ra)
