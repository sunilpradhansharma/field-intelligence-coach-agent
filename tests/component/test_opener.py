"""T035 — opener component tests (deterministic talking-point selection + LLM narration).

- Deterministic selection (seed 42): the chosen talking points + order are exactly as
  expected; the config cap is respected.
- Provenance/explainability (FR-010): every talking point records its source + ref, mirrored
  in the opener's reason.
- Suggestion-only (FR-011): the opener is data (text + points + reason), never an action.
- Anti-LLM guard: narration changes ONLY the wording (text + reason.summary); the talking
  points and provenance are byte-for-byte identical (the LLM added no points / facts).
- Edge case (FR-018): a no-priority rep gets the positive default opener, not a fabricated one.
"""

from dataclasses import replace

from coach.components.accounts_context import accounts_context_for_rep
from coach.components.coaching_focus import coaching_focus_for_rep
from coach.components.opener import PENDING_SUMMARY, PENDING_TEXT, build_opener
from coach.components.ranking import rank_reps
from coach.config.settings import DEFAULT_FOCUS_AREA, DEFAULT_OPENER_POINT, get_settings
from coach.data_access.interface import AccessContext
from coach.data_access.sqlite_store import SqliteStore
from coach.llm.narrate import narrate_opener
from coach.schemas import CoachingFocus, OpenerSource, Reason, RepRanking, Role
from coach.synthetic import generate

SEED = 42


class FakeLLM:
    def __init__(self, text: str = "Let's start with where the business is heading today."):
        self.text = text
        self.calls: list[dict] = []

    def narrate(self, reason_input: dict, instruction: str) -> str:
        self.calls.append(reason_input)
        return self.text


def _ctx():
    return AccessContext(
        user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
    )


def _sections(store, rep_id):
    """Assemble the upstream section outputs (as the orchestrator would) for one rep."""
    ranking = {r.rep_id: r for r in rank_reps(_ctx(), store)}[rep_id]
    focus = coaching_focus_for_rep(_ctx(), store, rep_id)
    accounts = accounts_context_for_rep(_ctx(), store, rep_id)
    return ranking, focus, accounts


def _store():
    s = SqliteStore(":memory:")
    s.write_dataset(generate(SEED))
    return s


# ------------------------------------------------- deterministic talking-point selection
def test_talking_points_match_seeded_example():
    s = _store()
    settings = get_settings()
    op = build_opener(*_sections(s, "rep_d1_001"))
    # Built from the top coaching focus, the key mismatch account (LILETTA), and the priority.
    assert [(p.source.value, p.ref) for p in op.talking_points] == [
        ("coaching_focus", settings.focus_catalog["declining_share"]),
        ("account_mismatch", "acct_rep_d1_001_03/LILETTA"),
        ("priority", "rep_d1_001"),
    ]
    assert "LILETTA" in op.talking_points[1].text
    assert op.text == PENDING_TEXT and op.reason.summary == PENDING_SUMMARY  # not yet narrated
    s.close()


def test_config_cap_is_respected():
    s = _store()
    one = replace(get_settings(), opener_max_points=1)
    op = build_opener(*_sections(s, "rep_d1_001"), settings=one)
    assert len(op.talking_points) == 1
    s.close()


# ------------------------------------------------------------ provenance / explainability
def test_every_talking_point_has_provenance():
    s = _store()
    op = build_opener(*_sections(s, "rep_d1_001"))
    for p in op.talking_points:
        assert p.source in OpenerSource and p.ref and p.text
    # The reason mirrors each point's provenance (FR-010).
    assert [d.value for d in op.reason.data_points] == [p.ref for p in op.talking_points]
    s.close()


def test_opener_is_suggestion_only():
    s = _store()
    op = build_opener(*_sections(s, "rep_d1_001"))
    # Pure data — text + points + reason, no action/execute field (FR-011).
    assert set(op.model_dump().keys()) == {"text", "talking_points", "reason"}
    s.close()


# -------------------------------------------------------------------- anti-LLM guard
def test_narration_changes_only_wording():
    s = _store()
    op = build_opener(*_sections(s, "rep_d1_001"))
    fake = FakeLLM()
    out = narrate_opener(op, fake)

    b, a = op.model_dump(), out.model_dump()
    # Facts identical — the LLM added no talking points and changed no provenance.
    assert a["talking_points"] == b["talking_points"]
    assert a["reason"]["data_points"] == b["reason"]["data_points"]
    # Only the wording changed.
    assert b["text"] == PENDING_TEXT and b["reason"]["summary"] == PENDING_SUMMARY
    assert a["text"] == fake.text and a["reason"]["summary"] == fake.text
    a["text"], a["reason"]["summary"] = b["text"], b["reason"]["summary"]
    assert a == b
    s.close()


# ------------------------------------------------------------------ edge case (FR-018)
def test_no_priority_rep_gets_positive_default_opener():
    # No real coaching focus, no accounts, no ranking signals -> positive default, not invented.
    rr = RepRanking(
        rep_id="rep_x",
        rank=1,
        total_score=0.0,
        reason=Reason(summary="no signals", signals=[], data_points=[]),
    )
    cf = [CoachingFocus(focus_area=DEFAULT_FOCUS_AREA, reason=Reason(summary="no gap"))]
    op = build_opener(rr, cf, [])
    assert len(op.talking_points) == 1
    tp = op.talking_points[0]
    assert tp.source == OpenerSource.default
    assert tp.text == DEFAULT_OPENER_POINT
    assert op.reason.data_points  # carries a clear provenance note, not fabricated
