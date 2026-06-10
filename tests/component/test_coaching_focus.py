"""T026 — coaching-focus component tests (deterministic selection + LLM narration).

- Example-based (seed 42): the chosen focus areas and their order are exactly as expected;
  changing a config threshold changes the selection predictably.
- Explainability (FR-010): every CoachingFocus has a non-empty structured reason with >=1
  data point.
- Anti-LLM guard: narration changes ONLY reason.summary.
- Edge cases: a no-signal rep returns a sensible default with a reason; a no-history rep is
  handled gracefully (FR-018).

The LLM is a fake (no live Bedrock calls), so these tests are deterministic.
"""

from dataclasses import replace

import pytest

from coach.components.coaching_focus import PENDING_SUMMARY, coaching_focus_for_rep
from coach.config.settings import DEFAULT_FOCUS_AREA, get_settings
from coach.data_access.interface import AccessContext
from coach.data_access.sqlite_store import SqliteStore
from coach.llm.narrate import narrate_focuses
from coach.schemas import Role
from coach.synthetic import generate

SEED = 42


class FakeLLM:
    def __init__(self, text: str = "Synthetic narrated focus reason."):
        self.text = text
        self.calls: list[dict] = []

    def narrate(self, reason_input: dict, instruction: str) -> str:
        self.calls.append(reason_input)
        return self.text


def _dm_ctx() -> AccessContext:
    return AccessContext(
        user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
    )


@pytest.fixture
def store():
    ds = generate(SEED)
    s = SqliteStore(":memory:")
    s.write_dataset(ds)
    yield s, ds
    s.close()


# --------------------------------------------------------- T026 example-based selection
# Expected focus areas per rep, as SIGNAL keys (mapped to catalog wording in the assertion),
# strongest first then fixed signal order. Default = the no-gap focus.
EXPECTED_BY_SIGNAL = {
    "rep_d1_001": ["declining_share", "low_call_activity", "opportunity_risk"],
    "rep_d1_003": ["declining_share", "low_call_activity", "opportunity_risk"],
    "rep_d1_008": ["opportunity_risk", "low_call_activity"],
}
DEFAULT_REP = "rep_d1_002"


def test_focus_selection_matches_seeded_example(store):
    s, _ = store
    settings = get_settings()
    for rep_id, signal_keys in EXPECTED_BY_SIGNAL.items():
        focuses = coaching_focus_for_rep(_dm_ctx(), s, rep_id, settings)
        assert 1 <= len(focuses) <= settings.max_focus_areas
        expected = [settings.focus_catalog[k] for k in signal_keys]
        assert [f.focus_area for f in focuses] == expected


def test_changing_a_threshold_changes_selection(store):
    s, _ = store
    base = get_settings()
    # rep_d1_008 triggers opportunity_risk (strongest) + low_call_activity.
    before = [f.focus_area for f in coaching_focus_for_rep(_dm_ctx(), s, "rep_d1_008", base)]
    assert base.focus_catalog["opportunity_risk"] in before

    # Raise the opportunity_risk threshold above the rep's raw value -> that focus drops out.
    tightened = replace(base, focus_thresholds={**base.focus_thresholds, "opportunity_risk": 999.0})
    after = [f.focus_area for f in coaching_focus_for_rep(_dm_ctx(), s, "rep_d1_008", tightened)]
    assert base.focus_catalog["opportunity_risk"] not in after
    assert base.focus_catalog["low_call_activity"] in after  # the other focus remains


# ------------------------------------------------------------------ explainability (FR-010)
def test_every_focus_has_structured_reason(store):
    s, ds = store
    d1_reps = [r.rep_id for r in ds.reps if r.district_id == "D1"]
    for rep_id in d1_reps:
        focuses = coaching_focus_for_rep(_dm_ctx(), s, rep_id)
        assert 1 <= len(focuses) <= 3
        for f in focuses:
            assert f.focus_area  # non-empty
            assert f.reason.summary  # non-empty (placeholder until narrated)
            assert len(f.reason.data_points) >= 1  # at least one data point behind it


# ---------------------------------------------------------- anti-LLM guard (FR-005/FR-010)
def test_narration_changes_only_summary(store):
    s, _ = store
    focuses = coaching_focus_for_rep(_dm_ctx(), s, "rep_d1_001")
    fake = FakeLLM("Share is slipping at key accounts; coach on defending and regrowing it.")
    narrated = narrate_focuses(focuses, fake)

    assert len(fake.calls) == len(focuses)
    for before, after in zip(focuses, narrated, strict=True):
        b, a = before.model_dump(), after.model_dump()
        assert a["focus_area"] == b["focus_area"]
        assert a["reason"]["signals"] == b["reason"]["signals"]
        assert a["reason"]["data_points"] == b["reason"]["data_points"]
        assert b["reason"]["summary"] == PENDING_SUMMARY
        assert (
            a["reason"]["summary"]
            == "Share is slipping at key accounts; coach on defending and regrowing it."
        )
        a["reason"]["summary"] = b["reason"]["summary"]
        assert a == b


# ------------------------------------------------------------------ edge cases (FR-018)
def test_no_signal_rep_returns_default_focus(store):
    s, _ = store
    focuses = coaching_focus_for_rep(_dm_ctx(), s, DEFAULT_REP)
    assert len(focuses) == 1
    assert focuses[0].focus_area == DEFAULT_FOCUS_AREA
    assert focuses[0].reason.data_points  # has a clear note, not empty
    assert any("threshold" in dp.label for dp in focuses[0].reason.data_points)


def test_no_history_rep_is_handled_gracefully(store):
    s, ds = store
    reps_with_history = {sess.rep_id for sess in ds.coaching_sessions}
    no_history = [
        r.rep_id for r in ds.reps if r.district_id == "D1" and r.rep_id not in reps_with_history
    ]
    assert no_history, "expected a no-history rep in District 1 (edge case)"
    rep_id = no_history[0]

    # Does not crash; returns valid focuses; never a missed-follow-up focus (no history).
    settings = get_settings()
    focuses = coaching_focus_for_rep(_dm_ctx(), s, rep_id, settings)
    assert focuses
    assert settings.focus_catalog["missed_follow_up"] not in [f.focus_area for f in focuses]

    # With no signals clearing the threshold, the default focus states the missing history.
    no_signals = replace(settings, focus_thresholds={k: 1e9 for k in settings.focus_thresholds})
    default = coaching_focus_for_rep(_dm_ctx(), s, rep_id, no_signals)
    assert len(default) == 1 and default[0].focus_area == DEFAULT_FOCUS_AREA
    assert any("history" in dp.label for dp in default[0].reason.data_points)
