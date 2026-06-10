"""T011 — coaching-notes retriever tests: determinism, RBAC, PRP, config/offline.

The retriever is the vector-search path of the single door — it MUST enforce the same RBAC
scope and PRP scrubbing as the structured reads (ADR 0002). Uses FakeEmbeddings + an in-memory
store so the tests are deterministic and make NO live Bedrock calls.
"""

import pytest

from coach.data_access.interface import AccessContext, Retriever, ScopeError
from coach.data_access.notes_retriever import NotesRetriever
from coach.data_access.sqlite_store import SqliteStore
from coach.llm.embeddings import BedrockEmbeddings, FakeEmbeddings
from coach.schemas import Role
from coach.synthetic import generate

SEED = 42
QUERY = "account prioritization approved assets"


def _build_retriever():
    ds = generate(SEED)
    store = SqliteStore(":memory:")
    store.write_dataset(ds)
    r = NotesRetriever(store, FakeEmbeddings())
    r.index()
    return store, ds, r


def _dm_ctx():
    return AccessContext(
        user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
    )


def _region_ctx():
    return AccessContext(user_id="region_r1", role=Role.regional_director, region_id="R1")


def _all_ctx():
    return AccessContext(user_id="hos_1", role=Role.head_of_sales, region_id="R1")


@pytest.fixture
def retriever():
    store, ds, r = _build_retriever()
    yield store, ds, r
    store.close()


def test_implements_retriever_protocol(retriever):
    _, _, r = retriever
    assert isinstance(r, Retriever)


# ---------------------------------------------------------------------- determinism
def test_same_query_returns_same_notes(retriever):
    _, ds, r = retriever
    rep = next(s.rep_id for s in ds.coaching_sessions)
    a = [n.session_id for n in r.search_notes(_all_ctx(), rep, QUERY, k=3)]
    b = [n.session_id for n in r.search_notes(_all_ctx(), rep, QUERY, k=3)]
    assert a == b and a  # stable and non-empty


def test_two_seeded_builds_agree(retriever):
    _, ds, r1 = retriever
    store2, _, r2 = _build_retriever()
    rep = next(s.rep_id for s in ds.coaching_sessions)
    assert [n.session_id for n in r1.search_notes(_all_ctx(), rep, QUERY, k=3)] == [
        n.session_id for n in r2.search_notes(_all_ctx(), rep, QUERY, k=3)
    ]
    store2.close()


# ---------------------------------------------------------------------------- RBAC
def test_dm_cannot_retrieve_other_district(retriever):
    _, ds, r = retriever
    d2_rep = next(rp.rep_id for rp in ds.reps if rp.district_id == "D2")
    with pytest.raises(ScopeError):
        r.search_notes(_dm_ctx(), d2_rep, QUERY)


def test_dm_can_retrieve_own_district(retriever):
    _, ds, r = retriever
    d1_rep_with_notes = next(
        s.rep_id for s in ds.coaching_sessions if s.rep_id.startswith("rep_d1")
    )
    notes = r.search_notes(_dm_ctx(), d1_rep_with_notes, QUERY)
    assert all(n.rep_id == d1_rep_with_notes for n in notes)


def test_region_retrieves_across_its_region(retriever):
    _, ds, r = retriever
    d1 = next(s.rep_id for s in ds.coaching_sessions if s.rep_id.startswith("rep_d1"))
    d2 = next(s.rep_id for s in ds.coaching_sessions if s.rep_id.startswith("rep_d2"))
    # A region role can retrieve for reps in BOTH districts of its region (no ScopeError).
    assert r.search_notes(_region_ctx(), d1, QUERY) is not None
    assert r.search_notes(_region_ctx(), d2, QUERY) is not None


def test_all_scope_retrieves_everywhere(retriever):
    _, ds, r = retriever
    for rep in {s.rep_id for s in ds.coaching_sessions}:
        notes = r.search_notes(_all_ctx(), rep, QUERY)
        assert all(n.rep_id == rep for n in notes)


# ----------------------------------------------------------------------------- PRP
def test_prp_tied_notes_exist_in_index(retriever):
    _, _, r = retriever
    assert r.prp_tied_session_ids(), "expected >=1 PRP-tied note so the PRP test is meaningful"


def test_prp_notes_never_returned_at_any_scope(retriever):
    _, ds, r = retriever
    prp_tied = r.prp_tied_session_ids()
    for ctx in (_dm_ctx(), _region_ctx(), _all_ctx()):
        for rep in {s.rep_id for s in ds.coaching_sessions}:
            try:
                notes = r.search_notes(ctx, rep, QUERY, k=20)
            except ScopeError:
                continue  # out of this caller's scope — fine
            assert prp_tied.isdisjoint({n.session_id for n in notes})


def test_prp_exclusion_is_selective(retriever):
    # The rep owning a PRP-tied note still returns its OTHER notes; only the PRP one is dropped.
    _, _, r = retriever
    prp_sid = sorted(r.prp_tied_session_ids())[0]
    owner = r._sessions[prp_sid].rep_id
    returned = {n.session_id for n in r.search_notes(_all_ctx(), owner, QUERY, k=20)}
    assert prp_sid not in returned  # PRP note excluded
    assert returned  # but the rep's non-PRP notes still come back (retrieval works)


# ----------------------------------------------------------------- config / offline
def test_bedrock_embeddings_model_id_from_config(monkeypatch):
    # No live call: just construction. Model id comes from config; raises if unset.
    monkeypatch.delenv("BEDROCK_EMBED_MODEL_ID", raising=False)
    with pytest.raises(ValueError):
        BedrockEmbeddings()
    emb = BedrockEmbeddings(model_id="amazon.titan-embed-text-v2:0")
    assert emb.model_id == "amazon.titan-embed-text-v2:0"
    assert emb._client is None  # boto3 not imported / no client created
