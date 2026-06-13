"""T038 / Step 5a — end-to-end brief assembly: the 5-section rubric, consistency, the
narrate-before-expose guard, RBAC + PRP at the brief level, and the FR-018 edge case.

Uses FakeEmbeddings + a deterministic FakeLLM so the whole brief is deterministic (no live
Bedrock).
"""

import pytest

from coach.data_access.interface import AccessContext, ScopeError
from coach.data_access.notes_retriever import NotesRetriever
from coach.data_access.sqlite_store import SqliteStore
from coach.llm.embeddings import FakeEmbeddings
from coach.orchestrator.assembly import (
    PENDING_PLACEHOLDERS,
    BriefNotNarratedError,
    assert_narrated,
    rubric_violations,
)
from coach.orchestrator.brief_graph import build_brief
from coach.schemas import EmptyState, RideAlongPrep, Role
from coach.synthetic import generate

SEED = 42


class FakeLLM:
    """Deterministic narrator — a fixed non-empty wording for every section."""

    def narrate(self, reason_input: dict, instruction: str) -> str:
        return "Narrated wording for this brief section."


class EmptyLLM:
    """Returns empty wording — narration leaves the placeholders in place (failure mode)."""

    def narrate(self, reason_input: dict, instruction: str) -> str:
        return ""


def _dm_ctx():
    return AccessContext(
        user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
    )


def _build():
    ds = generate(SEED)
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


# --------------------------------------------------------------- 5-section rubric (SC-002)
def test_assembled_brief_passes_the_five_section_rubric(env):
    store, _, r = env
    brief = build_brief(_dm_ctx(), store, r, FakeLLM())
    # All five sections present.
    assert brief.ranked_reps and brief.selected_rep_id and brief.coaching_focus
    assert brief.ride_along_prep is not None and brief.accounts and brief.opener
    assert brief.synthetic is True
    # The rubric (sections present + every recommendation has a visible reason) passes.
    assert rubric_violations(brief) == []
    # And no narration placeholder survived (narrate-before-expose held).
    assert_narrated(brief)  # does not raise


def test_default_selection_is_the_top_ranked_rep(env):
    store, _, r = env
    brief = build_brief(_dm_ctx(), store, r, FakeLLM())
    assert brief.selected_rep_id == brief.ranked_reps[0].rep_id


def test_explicit_in_scope_rep_can_be_selected(env):
    store, _, r = env
    brief = build_brief(_dm_ctx(), store, r, FakeLLM(), rep_id="rep_d1_005")
    assert brief.selected_rep_id == "rep_d1_005"
    assert rubric_violations(brief) == []


# ------------------------------------------------------------- consistency (SC-004 / F4)
def test_brief_is_deterministic_across_runs(env):
    store, _, r = env
    a = build_brief(_dm_ctx(), store, r, FakeLLM())
    b = build_brief(_dm_ctx(), store, r, FakeLLM())
    assert a.model_dump() == b.model_dump()  # identical skeleton + facts + (deterministic) wording


# ------------------------------------------------------ narrate-before-expose guard
def test_guard_raises_on_an_un_narrated_section(env):
    store, _, r = env
    brief = build_brief(_dm_ctx(), store, r, FakeLLM())
    # Force one section back to a placeholder; the guard must catch it.
    brief.opener.reason.summary = next(iter(PENDING_PLACEHOLDERS))
    with pytest.raises(BriefNotNarratedError):
        assert_narrated(brief)


def test_assembly_refuses_to_return_an_un_narrated_brief(env):
    store, _, r = env
    # An LLM that returns nothing leaves every section's placeholder -> assembly must RAISE.
    with pytest.raises(BriefNotNarratedError):
        build_brief(_dm_ctx(), store, r, EmptyLLM())


# --------------------------------------------------------------- RBAC + PRP at brief level
def test_out_of_scope_rep_raises_scope_error(env):
    store, ds, r = env
    d2_rep = next(rp.rep_id for rp in ds.reps if rp.district_id == "D2")
    with pytest.raises(ScopeError):
        build_brief(_dm_ctx(), store, r, FakeLLM(), rep_id=d2_rep)


def test_prp_accounts_never_appear_in_the_brief(env):
    store, ds, r = env
    prp_ids = {a.account_id for a in ds.accounts if a.prp}
    assert prp_ids  # guard: PRP accounts exist in the seed
    # Build a brief for every in-scope rep and check the accounts section.
    for rep in (rp.rep_id for rp in ds.reps if rp.district_id == "D1"):
        brief = build_brief(_dm_ctx(), store, r, FakeLLM(), rep_id=rep)
        assert prp_ids.isdisjoint({a.account_id for a in brief.accounts})


# ------------------------------------------------------------------- FR-018 edge case
def test_no_history_rep_still_produces_a_valid_rubric_passing_brief(env):
    store, ds, r = env
    reps_with = {s.rep_id for s in ds.coaching_sessions}
    no_history = next(
        rp.rep_id for rp in ds.reps if rp.district_id == "D1" and rp.rep_id not in reps_with
    )
    brief = build_brief(_dm_ctx(), store, r, FakeLLM(), rep_id=no_history)
    assert isinstance(brief.ride_along_prep, EmptyState)  # empty-state, not fabricated
    assert rubric_violations(brief) == []  # the brief is still complete and rubric-passing


def test_brief_is_suggestion_only_pure_data(env):
    store, _, r = env
    brief = build_brief(_dm_ctx(), store, r, FakeLLM())
    # Pure data — the dump round-trips and carries no action/execute path (FR-011).
    keys = set(brief.model_dump().keys())
    assert keys == {
        "brief_id",
        "generated_for",
        "ranked_reps",
        "selected_rep_id",
        "coaching_focus",
        "ride_along_prep",
        "accounts",
        "covariant",  # Phase 9 section-4 insight (capability #4) — pure data, suggestion-only
        "opener",
        "synthetic",
    }
    # The ride-along section is one of the two declared shapes (data, not an action).
    assert isinstance(brief.ride_along_prep, (RideAlongPrep, EmptyState))
