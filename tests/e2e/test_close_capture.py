"""Phase 10 Step 10b — voice capture on top of the Step 10a write path (P10-T5).

Covers: the transcription seam (deterministic FakeTranscriber, no live AWS); structuring fidelity
(Claude organizes the DM's words and does NOT fabricate — observations stay verbatim, unstated
fields are empty); review-before-save (the draft is returned, not persisted, and the DM's edit is
what gets saved); save-path reuse (saving the draft goes through the SAME 10a write path with
writer-scope RBAC, out-of-scope rejected like not-found); PRP-on-readback; and the loop closing
via voice. FakeLLM + FakeTranscriber — no live Bedrock / Transcribe.
"""

import json

import pytest
from pydantic import ValidationError

from coach.components.close_capture import draft_close_record, draft_close_record_from_voice
from coach.components.ride_along_prep import ride_along_prep_for_rep
from coach.data_access.interface import AccessContext, ScopeError
from coach.data_access.notes_retriever import NotesRetriever
from coach.data_access.sqlite_store import SqliteStore
from coach.llm.embeddings import FakeEmbeddings
from coach.llm.transcribe import AmazonTranscribe, FakeTranscriber, Transcriber
from coach.schemas import RideAlongPrep, Role
from coach.synthetic import generate

SEED = 42


class JsonLLM:
    """A FakeLLM that returns a controllable structuring response (JSON, or raw garbage)."""

    def __init__(self, agreed=None, observe=None, raw=None):
        self.raw = raw
        self.agreed = agreed or []
        self.observe = observe or []

    def narrate(self, reason_input: dict, instruction: str) -> str:
        if self.raw is not None:
            return self.raw
        return json.dumps({"agreed_actions": self.agreed, "observe_next": self.observe})


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


def _non_prp(ds, rep_id: str) -> str:
    return next(a.account_id for a in ds.accounts if a.rep_id == rep_id and not a.prp)


def _prp_rep_and_account(ds) -> tuple[str, str]:
    a = next(a for a in ds.accounts if a.prp and a.rep_id.startswith("rep_d1"))
    return a.rep_id, a.account_id


def _voice_draft(
    rep_id,
    *,
    transcript="Strong opening today. Agreed to roleplay objection handling.",
    llm=None,
    account_id=None,
):
    llm = llm or JsonLLM(agreed=["Roleplay objection handling"], observe=["Confirm pre-call plans"])
    return draft_close_record_from_voice(
        FakeTranscriber(transcript),
        b"AUDIO-BYTES",
        llm,
        rep_id=rep_id,
        date="2026-06-09",
        account_id=account_id,
    )


# ----------------------------------------------------------------- transcription seam
def test_fake_transcriber_is_deterministic_and_offline():
    tr = FakeTranscriber("Strong opening today.")
    assert isinstance(tr, Transcriber)
    assert tr.transcribe(b"AUDIO-1") == "Strong opening today."
    assert (
        tr.transcribe(b"totally different bytes") == "Strong opening today."
    )  # fixed, no AWS call


def test_amazon_transcribe_constructs_without_aws_lazily():
    # Constructing the real provider must not import boto3 or need creds (lazy); region from config.
    t = AmazonTranscribe(region="us-east-1", s3_bucket="bucket")
    assert isinstance(t, Transcriber)
    assert t.region == "us-east-1" and t.s3_bucket == "bucket"  # no client built yet


# ------------------------------------------------- structuring fidelity (no fabrication)
def test_draft_is_structured_from_the_transcript():
    llm = JsonLLM(agreed=["Roleplay objection handling"], observe=["Confirm pre-call plans"])
    draft = draft_close_record("DM's exact words.", llm, rep_id="rep_d1_001", date="2026-06-09")
    assert draft.observations == "DM's exact words."  # verbatim
    assert draft.agreed_actions == ["Roleplay objection handling"]
    assert draft.observe_next == ["Confirm pre-call plans"]


def test_draft_does_not_fabricate_unstated_fields():
    # The DM stated no actions -> the draft's lists are EMPTY, not invented.
    draft = draft_close_record(
        "Just an observation, nothing agreed.",
        JsonLLM(agreed=[], observe=[]),
        rep_id="rep_d1_001",
        date="2026-06-09",
    )
    assert draft.agreed_actions == [] and draft.observe_next == []
    assert draft.observations == "Just an observation, nothing agreed."


def test_unparseable_llm_output_yields_empty_lists_not_fabrication():
    draft = draft_close_record(
        "The DM said things.",
        JsonLLM(raw="not json at all"),
        rep_id="rep_d1_001",
        date="2026-06-09",
    )
    assert draft.agreed_actions == [] and draft.observe_next == []  # fallback structures nothing
    assert draft.observations == "The DM said things."  # verbatim preserved


def test_observations_are_always_verbatim_the_llm_cannot_alter_them():
    # Even if the LLM tries to supply an "observations" field, it is IGNORED — observations are the
    # DM's exact transcript, so the core record can never contain words the DM did not say.
    sneaky = JsonLLM(
        raw=json.dumps(
            {"observations": "INVENTED TEXT", "agreed_actions": ["x"], "observe_next": []}
        )
    )
    draft = draft_close_record("EXACT DM WORDS.", sneaky, rep_id="rep_d1_001", date="2026-06-09")
    assert draft.observations == "EXACT DM WORDS."
    assert "INVENTED" not in draft.observations
    assert draft.agreed_actions == ["x"]


def test_empty_transcript_is_rejected():
    with pytest.raises(ValidationError):
        draft_close_record("   ", JsonLLM(), rep_id="rep_d1_001", date="2026-06-09")


# ------------------------------------------------- review before save + save-path reuse
def test_voice_draft_is_reviewable_not_saved_until_the_dm_saves(env):
    store, ds = env
    dm = _dm_ctx()
    draft = _voice_draft("rep_d1_001", account_id=_non_prp(ds, "rep_d1_001"))
    # The draft is NOT persisted yet (the DM reviews/edits first).
    before = {s.session_id for s in store.get_coaching_sessions(dm, "rep_d1_001")}
    assert draft.session_id not in before

    # The DM edits the draft, then saves through the EXISTING Step 10a write path.
    edited = draft.model_copy(
        update={"agreed_actions": ["Roleplay objection handling (DM-edited)"]}
    )
    saved = store.save_close_record(dm, edited)
    assert saved.author_user_id == "dm_d1"  # author stamped from context by the 10a path
    note = {s.session_id: s for s in store.get_coaching_sessions(dm, "rep_d1_001")}[
        saved.session_id
    ]
    assert note.agreed_actions == [
        "Roleplay objection handling (DM-edited)"
    ]  # the DM's edit was saved


def test_voice_save_enforces_writer_scope_rbac_like_not_found(env):
    store, ds = env
    d2_rep = next(r.rep_id for r in ds.reps if r.district_id == "D2")
    # A DM (D1) cannot save a voice draft for an out-of-scope rep, nor for a non-existent rep —
    # both raise the same ScopeError (10a's writer-scope RBAC; existence never leaked).
    with pytest.raises(ScopeError):
        store.save_close_record(_dm_ctx(), _voice_draft(d2_rep))
    with pytest.raises(ScopeError):
        store.save_close_record(_dm_ctx(), _voice_draft("rep_d1_999"))


# --------------------------------------------------------------- the loop closes via voice
def test_loop_closes_via_voice(env):
    store, ds = env
    dm = _dm_ctx()
    draft = _voice_draft(
        "rep_d1_001",
        transcript="Strong opening today. Agreed to roleplay objection handling.",
        account_id=_non_prp(ds, "rep_d1_001"),
    )
    store.save_close_record(dm, draft)

    retriever = NotesRetriever(store, FakeEmbeddings())
    retriever.index()
    prep = ride_along_prep_for_rep(dm, store, retriever, "rep_d1_001")
    assert isinstance(prep, RideAlongPrep)
    # The voice-captured observations + the extracted action surface via the scoped + PRP read.
    assert any("Strong opening" in n.text for n in prep.prior_notes)
    assert any("objection handling" in a.text.lower() for a in prep.agreed_actions)


# --------------------------------------------------------- PRP still holds on the voice path
def test_voice_close_tied_to_prp_account_is_fully_scrubbed_on_readback(env):
    store, ds = env
    prp_rep, prp_account = _prp_rep_and_account(ds)
    writer = _dm_ctx() if prp_rep.startswith("rep_d1") else _hos_ctx()
    saved = store.save_close_record(
        writer,
        _voice_draft(
            prp_rep,
            transcript="PRP note SECRET_MARKER.",
            llm=JsonLLM(agreed=["agreed SECRET_MARKER"], observe=["observe SECRET_MARKER"]),
            account_id=prp_account,
        ),
    )
    retriever = NotesRetriever(store, FakeEmbeddings())
    retriever.index()
    for ctx in (_dm_ctx(), _region_ctx(), _hos_ctx()):
        prep = ride_along_prep_for_rep(ctx, store, retriever, prp_rep)
        if not isinstance(prep, RideAlongPrep):
            continue
        blob = " ".join(
            [n.text for n in prep.prior_notes]
            + [a.text for a in prep.agreed_actions]
            + [o.text for o in prep.observe_next]
        )
        ids = (
            {n.session_id for n in prep.prior_notes}
            | {a.session_id for a in prep.agreed_actions}
            | {o.session_id for o in prep.observe_next}
        )
        assert "SECRET_MARKER" not in blob  # no field of the PRP voice note surfaces
        assert saved.session_id not in ids  # nor its id
