"""Phase 10 Step 10a — the CLOSE write path (text first; P10-T1/T2/T3/T4).

The write is the sensitive part. These assert: writer-scope RBAC on the WRITE (same as reads;
out-of-scope -> ScopeError, indistinguishable from not-found); the loop closes (a saved CLOSE
record surfaces in the next ride-along prep through the EXISTING scoped + PRP-scrubbed readback);
PRP-on-readback (a close note tied to a PRP HCP is scrubbed, ADR 0002); validation; and that the
write merely RECORDS the DM's own input (no autonomous action). Seeded + deterministic, no live
calls.
"""

import pytest
from pydantic import ValidationError

from coach.components.ride_along_prep import ride_along_prep_for_rep
from coach.data_access.interface import AccessContext, ScopeError
from coach.data_access.notes_retriever import NotesRetriever
from coach.data_access.sqlite_store import SqliteStore
from coach.llm.embeddings import FakeEmbeddings
from coach.schemas import CloseRecord, RideAlongPrep, Role, ScopeLevel
from coach.synthetic import generate

SEED = 42


def _dm_ctx() -> AccessContext:
    return AccessContext(
        user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
    )


def _region_ctx() -> AccessContext:
    return AccessContext(user_id="region_r1", role=Role.regional_director, region_id="R1")


def _hos_ctx() -> AccessContext:
    return AccessContext(user_id="hos_1", role=Role.head_of_sales, region_id="R1")


@pytest.fixture
def env():
    ds = generate(SEED)
    store = SqliteStore(":memory:")
    store.write_dataset(ds)
    yield store, ds
    store.close()


def _non_prp_account(ds, rep_id: str) -> str:
    return next(a.account_id for a in ds.accounts if a.rep_id == rep_id and not a.prp)


def _prp_rep_and_account(ds) -> tuple[str, str]:
    a = next(a for a in ds.accounts if a.prp and a.rep_id.startswith("rep_d1"))
    return a.rep_id, a.account_id


def _close(rep_id: str, **kw) -> CloseRecord:
    # session_id is left to default to a fresh UNIQUE id (collision-free) unless a test injects one.
    base = dict(
        rep_id=rep_id,
        date="2026-06-09",
        observations="Strong opening; objection handling needs work.",
        agreed_actions=["Roleplay objection handling next week"],
        observe_next=["Confirm pre-call plans for the top accounts"],
    )
    base.update(kw)
    return CloseRecord(**base)


# --------------------------------------------------------------- writer-scope RBAC (P10-T2)
def test_in_scope_write_succeeds_and_stamps_the_author(env):
    store, ds = env
    saved = store.save_close_record(
        _dm_ctx(), _close("rep_d1_001", account_id=_non_prp_account(ds, "rep_d1_001"))
    )
    # The author is stamped from the authenticated context (cannot be spoofed).
    assert saved.author_user_id == "dm_d1"
    assert saved.author_scope_level == ScopeLevel.district
    assert saved.observations == "Strong opening; objection handling needs work."


def test_out_of_scope_write_raises_scope_error_indistinguishable_from_not_found(env):
    store, ds = env
    d2_rep = next(r.rep_id for r in ds.reps if r.district_id == "D2")
    # A DM writing for another district's rep, and for a rep that does not exist, both raise the
    # SAME ScopeError (existence is never revealed) — exactly like a read.
    with pytest.raises(ScopeError):
        store.save_close_record(_dm_ctx(), _close(d2_rep))
    with pytest.raises(ScopeError):
        store.save_close_record(_dm_ctx(), _close("rep_d1_999"))


def test_region_and_all_writers_can_write_within_scope(env):
    store, ds = env
    assert (
        store.save_close_record(_region_ctx(), _close("rep_d1_001")).author_scope_level
        == ScopeLevel.region
    )
    d2_rep = next(r.rep_id for r in ds.reps if r.district_id == "D2")
    assert store.save_close_record(_hos_ctx(), _close(d2_rep)).author_scope_level == ScopeLevel.all_


# --------------------------------------------------------- the loop closes (P10-T2 readback)
def test_saved_close_record_surfaces_in_the_next_ride_along(env):
    store, ds = env
    dm = _dm_ctx()
    store.save_close_record(dm, _close("rep_d1_001", account_id=_non_prp_account(ds, "rep_d1_001")))

    # Re-index the retriever (build-time load) so the new note is available — the SAME scoped +
    # PRP-scrubbed readback path, no second path.
    retriever = NotesRetriever(store, FakeEmbeddings())
    retriever.index()
    prep = ride_along_prep_for_rep(dm, store, retriever, "rep_d1_001")

    assert isinstance(prep, RideAlongPrep)
    assert any("objection handling needs work" in n.text for n in prep.prior_notes)  # the note
    assert "Roleplay objection handling next week" in [a.text for a in prep.agreed_actions]
    assert "Confirm pre-call plans for the top accounts" in [o.text for o in prep.observe_next]


# ------------------------------------------------------- PRP on readback (P10-T3, ADR 0002)
def test_prp_tied_close_note_is_fully_scrubbed_on_readback_at_every_scope(env):
    store, ds = env
    prp_rep, prp_account = _prp_rep_and_account(ds)
    # A PRP-tied close record with a marker in EVERY field — body, agreed_actions, observe_next.
    saved = store.save_close_record(
        _dm_ctx() if prp_rep.startswith("rep_d1") else _hos_ctx(),
        _close(
            prp_rep,
            observations="PRP-tied note SECRET_MARKER.",
            agreed_actions=["agreed SECRET_MARKER"],
            observe_next=["observe SECRET_MARKER"],
            account_id=prp_account,
        ),
    )
    retriever = NotesRetriever(store, FakeEmbeddings())
    retriever.index()

    # NONE of the PRP record's fields may surface — free text, structured fields, OR its id —
    # at any scope level (the WHOLE record is scrubbed on readback; ADR 0002 / FR-020).
    for ctx in (_dm_ctx(), _region_ctx(), _hos_ctx()):
        prep = ride_along_prep_for_rep(ctx, store, retriever, prp_rep)
        if not isinstance(prep, RideAlongPrep):
            continue  # an EmptyState surfaces nothing — also fine
        note_texts = " ".join(n.text for n in prep.prior_notes)
        agreed_texts = " ".join(a.text for a in prep.agreed_actions)
        observe_texts = " ".join(o.text for o in prep.observe_next)
        surfaced_ids = (
            {n.session_id for n in prep.prior_notes}
            | {a.session_id for a in prep.agreed_actions}
            | {o.session_id for o in prep.observe_next}
        )
        assert "SECRET_MARKER" not in note_texts  # free-text body scrubbed
        assert "SECRET_MARKER" not in agreed_texts  # structured agreed_actions scrubbed
        assert "SECRET_MARKER" not in observe_texts  # structured observe_next scrubbed
        assert saved.session_id not in surfaced_ids  # the PRP record's id never surfaces


# ------------------------------------------------------------------- validation (P10-T4)
def test_malformed_close_record_is_rejected():
    with pytest.raises(ValidationError):
        CloseRecord(
            rep_id="rep_d1_001", session_id="s", date="2026-06-09", observations=""
        )  # empty body
    with pytest.raises(ValidationError):
        CloseRecord(session_id="s", date="2026-06-09", observations="x")  # missing rep_id


# --------------------------------------- records the human's input, not an autonomous action
def test_write_records_the_dms_input_verbatim(env):
    store, ds = env
    dm = _dm_ctx()
    record = _close(
        "rep_d1_001",
        observations="DM's exact words, unchanged.",
        account_id=_non_prp_account(ds, "rep_d1_001"),
    )
    saved = store.save_close_record(dm, record)

    # Read it back through the normal scoped path: the persisted note is the DM's input verbatim
    # (the system stored it; it did not generate or alter it — the human is the source of truth).
    sessions = {s.session_id: s for s in store.get_coaching_sessions(dm, "rep_d1_001")}
    note = sessions[saved.session_id]
    assert note.notes_text == "DM's exact words, unchanged."
    assert note.agreed_actions == ["Roleplay objection handling next week"]


# ------------------------------------------------ collision-free ids (FIX 2)
def test_close_record_ids_are_unique_and_do_not_cross_contaminate(env):
    store, ds = env
    dm = _dm_ctx()
    acct = _non_prp_account(ds, "rep_d1_001")
    # Two CLOSE records for the SAME rep with no explicit id -> distinct, collision-free ids.
    r1 = _close("rep_d1_001", observations="First close note ALPHA.", account_id=acct)
    r2 = _close("rep_d1_001", observations="Second close note BETA.", account_id=acct)
    assert r1.session_id != r2.session_id  # unique by default

    s1 = store.save_close_record(dm, r1)
    s2 = store.save_close_record(dm, r2)
    assert s1.session_id != s2.session_id

    # Both are persisted as DISTINCT notes — neither overwrites the other (no cross-contamination).
    sessions = {s.session_id: s for s in store.get_coaching_sessions(dm, "rep_d1_001")}
    assert s1.session_id in sessions and s2.session_id in sessions
    assert sessions[s1.session_id].notes_text == "First close note ALPHA."
    assert sessions[s2.session_id].notes_text == "Second close note BETA."
