"""T029 — ride-along prep component tests (deterministic assembly + RBAC/PRP + narration).

- Deterministic assembly (seed 42): expected prior notes / agreed actions / observe-next;
  the most-recent-N limit from config is respected.
- RBAC + PRP: out-of-scope rep -> ScopeError; a PRP-tied note (and its structured fields) is
  never surfaced (the note content comes through the RBAC+PRP-scrubbed retriever).
- Provenance/explainability (FR-010): every surfaced item records its source session + whether
  it came from the structured store or the retriever.
- Anti-LLM guard: narration changes ONLY the wording (reason.summary + opening).
- Edge cases (FR-018): no-history rep -> EmptyState; a missing field -> "not recorded".

FakeEmbeddings + in-memory store -> deterministic, no live Bedrock calls.
"""

from dataclasses import replace

import pytest

from coach.components.ride_along_prep import (
    NO_HISTORY_MESSAGE,
    NOT_RECORDED,
    PENDING_OPENING,
    PENDING_SUMMARY,
    ride_along_prep_for_rep,
)
from coach.config.settings import get_settings
from coach.data_access.interface import AccessContext, ScopeError
from coach.data_access.notes_retriever import NotesRetriever
from coach.data_access.sqlite_store import SqliteStore
from coach.llm.embeddings import FakeEmbeddings
from coach.schemas import EmptyState, NoteSource, RideAlongPrep, Role
from coach.synthetic import generate

SEED = 42


class FakeLLM:
    def __init__(self, text: str = "Synthetic narrated wording."):
        self.text = text
        self.calls: list[dict] = []

    def narrate(self, reason_input: dict, instruction: str) -> str:
        self.calls.append(reason_input)
        return self.text


def _dm_ctx():
    return AccessContext(
        user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
    )


def _build(ds=None):
    ds = ds or generate(SEED)
    store = SqliteStore(":memory:")
    store.write_dataset(ds)
    retriever = NotesRetriever(store, FakeEmbeddings())
    retriever.index()
    return store, ds, retriever


@pytest.fixture
def env():
    store, ds, retriever = _build()
    yield store, ds, retriever
    store.close()


# ----------------------------------------------------------- deterministic assembly
def test_assembles_recent_notes_and_structured_fields(env):
    store, _, r = env
    prep = ride_along_prep_for_rep(_dm_ctx(), store, r, "rep_d1_001")
    assert isinstance(prep, RideAlongPrep)
    # Two most-recent sessions, newest first; note text via the retriever.
    assert [n.session_id for n in prep.prior_notes] == ["sess_rep_d1_001_1", "sess_rep_d1_001_2"]
    assert all(n.source == NoteSource.retriever for n in prep.prior_notes)
    # Agreed actions / observe-next come from the structured store.
    assert prep.agreed_actions and all(
        a.source == NoteSource.structured_store for a in prep.agreed_actions
    )
    assert prep.observe_next and all(
        o.source == NoteSource.structured_store for o in prep.observe_next
    )
    # The structured items reference only the surfaced sessions.
    surfaced = {n.session_id for n in prep.prior_notes}
    assert {a.session_id for a in prep.agreed_actions} <= surfaced
    assert {o.session_id for o in prep.observe_next} <= surfaced


def test_most_recent_n_limit_from_config(env):
    store, _, r = env
    one = replace(get_settings(), ride_along_max_notes=1)
    prep = ride_along_prep_for_rep(_dm_ctx(), store, r, "rep_d1_001", one)
    assert len(prep.prior_notes) == 1
    assert prep.prior_notes[0].session_id == "sess_rep_d1_001_1"  # the most recent


def test_assembly_is_deterministic(env):
    store, _, r = env
    a = ride_along_prep_for_rep(_dm_ctx(), store, r, "rep_d1_001").model_dump()
    b = ride_along_prep_for_rep(_dm_ctx(), store, r, "rep_d1_001").model_dump()
    assert a == b


# ----------------------------------------------------------------- RBAC + PRP
def test_out_of_scope_rep_raises_scope_error(env):
    store, ds, r = env
    d2_rep = next(rp.rep_id for rp in ds.reps if rp.district_id == "D2")
    with pytest.raises(ScopeError):
        ride_along_prep_for_rep(_dm_ctx(), store, r, d2_rep)


def test_prp_tied_note_is_never_surfaced(env):
    store, ds, r = env
    prp_tied = r.prp_tied_session_ids()
    assert prp_tied  # non-vacuous
    # rep_d1_003 owns a PRP-tied session (sess_rep_d1_003_2) — it must not appear anywhere.
    prep = ride_along_prep_for_rep(_dm_ctx(), store, r, "rep_d1_003")
    surfaced_sessions = (
        {n.session_id for n in prep.prior_notes}
        | {a.session_id for a in prep.agreed_actions}
        | {o.session_id for o in prep.observe_next}
    )
    assert prp_tied.isdisjoint(surfaced_sessions)
    assert prep.prior_notes  # the rep's non-PRP notes still come back


# ------------------------------------------------------ provenance / explainability
def test_every_item_records_provenance(env):
    store, _, r = env
    prep = ride_along_prep_for_rep(_dm_ctx(), store, r, "rep_d1_001")
    for item in [*prep.prior_notes, *prep.agreed_actions, *prep.observe_next]:
        assert item.session_id and item.date and item.source in NoteSource
    # The reason documents the two data sources.
    sources = {dp.source for dp in prep.reason.data_points}
    assert {"retriever", "structured_store"} <= sources


# -------------------------------------------------------------- anti-LLM guard
def test_narration_changes_only_wording(env):
    from coach.llm.narrate import narrate_ride_along

    store, _, r = env
    prep = ride_along_prep_for_rep(_dm_ctx(), store, r, "rep_d1_001")
    fake = FakeLLM("Last time you agreed pre-call plans; open by checking progress.")
    out = narrate_ride_along(prep, fake)

    b, a = prep.model_dump(), out.model_dump()
    # Facts identical.
    assert a["prior_notes"] == b["prior_notes"]
    assert a["agreed_actions"] == b["agreed_actions"]
    assert a["observe_next"] == b["observe_next"]
    assert a["reason"]["data_points"] == b["reason"]["data_points"]
    # Only the wording changed.
    assert b["reason"]["summary"] == PENDING_SUMMARY and b["opening"] == PENDING_OPENING
    assert a["reason"]["summary"] == fake.text and a["opening"] == fake.text
    a["reason"]["summary"], a["opening"] = b["reason"]["summary"], b["opening"]
    assert a == b


# ------------------------------------------------------------ edge cases (FR-018)
def test_no_history_rep_returns_empty_state(env):
    store, ds, r = env
    reps_with = {s.rep_id for s in ds.coaching_sessions}
    no_history = next(
        rp.rep_id for rp in ds.reps if rp.district_id == "D1" and rp.rep_id not in reps_with
    )
    prep = ride_along_prep_for_rep(_dm_ctx(), store, r, no_history)
    assert isinstance(prep, EmptyState)
    assert prep.message == NO_HISTORY_MESSAGE and prep.has_history is False
    assert prep.reason.data_points  # carries a clear note, not fabricated


def test_empty_state_narration_sets_summary_only():
    from coach.llm.narrate import narrate_ride_along

    ds = generate(SEED)
    reps_with = {s.rep_id for s in ds.coaching_sessions}
    no_history = next(
        rp.rep_id for rp in ds.reps if rp.district_id == "D1" and rp.rep_id not in reps_with
    )
    store, _, r = _build(ds)
    empty = ride_along_prep_for_rep(_dm_ctx(), store, r, no_history)
    out = narrate_ride_along(empty, FakeLLM("This rep has no prior coaching history yet."))
    assert out.message == empty.message  # fact preserved
    assert out.reason.summary == "This rep has no prior coaching history yet."
    store.close()


def test_missing_observe_next_field_is_marked_not_recorded():
    ds = generate(SEED)
    # Clear observe_next on rep_d1_001's sessions to exercise the missing-field path.
    for s in ds.coaching_sessions:
        if s.rep_id == "rep_d1_001":
            s.observe_next = []
    store, _, r = _build(ds)
    prep = ride_along_prep_for_rep(_dm_ctx(), store, r, "rep_d1_001")
    assert prep.observe_next  # one "not recorded" item per surfaced session, never empty
    assert all(o.text == NOT_RECORDED for o in prep.observe_next)
    store.close()
