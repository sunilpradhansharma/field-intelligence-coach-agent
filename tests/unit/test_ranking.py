"""Phase 3 ranking tests (deterministic scorer + LLM narration).

- T020   — weights/determinism: score == weighted sum of signals; weights come from config;
           changing a weight changes the score predictably; same data -> same ranks/scores.
- T022   — explainability (FR-003): every RepRanking carries a structured reason with the
           four signal contributions and at least one top-contributor entry.
- T022a  — fairness (FR-017): perturbing a NON-signal attribute (tenure, name) leaves all
           ranks and scores unchanged.
- Anti-LLM-ranking guard (FR-002/FR-012): narration changes ONLY reason.summary.

The LLM is a fake (no live Bedrock calls), so these tests are deterministic.
"""

from dataclasses import replace

import pytest

from coach.components.ranking import CORE_SIGNALS, PENDING_SUMMARY, rank_reps
from coach.config.settings import (
    RANKING_HIGH_PRIORITY_CLOSING,
    RANKING_LOW_PRIORITY_CLOSING,
    RANKING_NO_GAP_SUMMARY,
    get_settings,
)
from coach.data_access.interface import AccessContext
from coach.data_access.sqlite_store import SqliteStore
from coach.llm.narrate import narrate_rankings, offline_ranking_summary
from coach.schemas import Role, SignalName
from coach.synthetic import generate

SEED = 42


class FakeLLM:
    """Deterministic stand-in for Claude — records calls, returns a fixed summary."""

    def __init__(self, text: str = "Synthetic narrated summary naming the top contributors."):
        self.text = text
        self.calls: list[dict] = []

    def narrate(self, reason_input: dict, instruction: str) -> str:
        self.calls.append(reason_input)
        return self.text


def _dm_ctx() -> AccessContext:
    return AccessContext(
        user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
    )


def _hos_ctx() -> AccessContext:
    return AccessContext(user_id="hos_1", role=Role.head_of_sales, region_id="R1")


@pytest.fixture
def store():
    ds = generate(SEED)
    s = SqliteStore(":memory:")
    s.write_dataset(ds)
    yield s, ds
    s.close()


# ------------------------------------------------------------------------- T020
def test_score_is_weighted_sum_of_normalized_signals(store):
    s, _ = store
    for r in rank_reps(_hos_ctx(), s):
        for sc in r.reason.signals:
            # Every signal is normalized into 0..1 so the weights alone control influence,
            # and each contribution is exactly normalized_value * weight.
            assert 0.0 <= sc.normalized_value <= 1.0
            assert sc.contribution == round(sc.normalized_value * sc.weight, 6)
        # Score is the sum of the (rounded) normalized contributions.
        assert r.total_score == round(sum(sc.contribution for sc in r.reason.signals), 6)


def test_changing_a_weight_changes_relative_influence(store):
    s, _ = store
    base = get_settings()
    base_by_id = {r.rep_id: r for r in rank_reps(_hos_ctx(), s, base)}

    # A rep with a positive low_call_activity signal — its score must move when we reweight.
    target = next(
        r
        for r in base_by_id.values()
        if any(
            sc.signal == SignalName.low_call_activity and sc.normalized_value > 0
            for sc in r.reason.signals
        )
    )
    norm = next(
        sc.normalized_value
        for sc in target.reason.signals
        if sc.signal == SignalName.low_call_activity
    )
    bumped_weights = {
        **base.ranking_weights,
        "low_call_activity": base.ranking_weights["low_call_activity"] + 1.0,
    }
    bumped = replace(base, ranking_weights=bumped_weights)
    bumped_by_id = {r.rep_id: r for r in rank_reps(_hos_ctx(), s, bumped)}

    # The score moves by exactly normalized_value * (delta weight) — relative influence is
    # controlled only by the weight (the normalized signal value is unchanged).
    delta = bumped_by_id[target.rep_id].total_score - base_by_id[target.rep_id].total_score
    assert delta == pytest.approx(norm * 1.0, abs=1e-5)


def test_signal_at_normalization_cap_contributes_exactly_its_weight(store):
    s, _ = store
    settings = get_settings()
    cap = settings.ranking_norm_caps["low_call_activity"]
    weight = settings.ranking_weights["low_call_activity"]

    # The seeded high-need rep has low_call_activity raw well above the cap (saturates to 1.0),
    # so its contribution for that signal equals exactly the weight.
    saturated = [
        sc
        for r in rank_reps(_hos_ctx(), s)
        for sc in r.reason.signals
        if sc.signal == SignalName.low_call_activity and sc.raw_value >= cap
    ]
    assert saturated, "expected at least one rep at/above the low_call_activity cap"
    for sc in saturated:
        assert sc.normalized_value == 1.0
        assert sc.contribution == pytest.approx(weight, abs=1e-6)


def test_ranking_is_deterministic_and_well_ordered(store):
    s, _ = store
    a = [r.model_dump() for r in rank_reps(_hos_ctx(), s)]
    b = [r.model_dump() for r in rank_reps(_hos_ctx(), s)]
    assert a == b  # same data -> identical ranks, scores, reasons
    assert [r["rank"] for r in a] == list(range(1, len(a) + 1))
    scores = [r["total_score"] for r in a]
    assert scores == sorted(scores, reverse=True)  # rank 1 = highest need


# ------------------------------------------------------------------------- T022
def test_every_ranking_has_structured_reason(store):
    s, _ = store
    for ctx in (_dm_ctx(), _hos_ctx()):
        rankings = rank_reps(ctx, s)
        assert rankings
        for r in rankings:
            assert r.reason.summary  # non-empty (FR-010)
            # Default config now ENABLES Summit (weight 0.2): the four CORE signals PLUS the
            # `summit_opportunity` 5th contributor; the four core are always present.
            signal_set = {sc.signal for sc in r.reason.signals}
            assert set(CORE_SIGNALS) <= signal_set
            assert SignalName.summit_opportunity in signal_set
            assert len(r.reason.signals) == 5
            assert len(r.reason.data_points) >= 1  # at least one top-contributor/explainer


# ------------------------------------------------------------------------ T022a
def test_perturbing_non_signal_attribute_does_not_change_ranking():
    base_ds = generate(SEED)
    base_store = SqliteStore(":memory:")
    base_store.write_dataset(base_ds)
    base = [r.model_dump() for r in rank_reps(_hos_ctx(), base_store)]

    # Perturb ONLY non-signal attributes: tenure_months and rep name.
    perturbed_ds = generate(SEED)
    for rep in perturbed_ds.reps:
        rep.tenure_months = rep.tenure_months + 100
        rep.name = rep.name + " (edited)"
    perturbed_store = SqliteStore(":memory:")
    perturbed_store.write_dataset(perturbed_ds)
    perturbed = [r.model_dump() for r in rank_reps(_hos_ctx(), perturbed_store)]

    assert base == perturbed  # ranks, scores, AND reasons identical
    base_store.close()
    perturbed_store.close()


# ------------------------------------------- anti-LLM-ranking guard (FR-002/FR-012)
def test_llm_narration_changes_only_summary(store):
    s, _ = store
    rankings = rank_reps(_hos_ctx(), s)
    fake = FakeLLM("Share is slipping in key accounts and a follow-up was missed.")
    narrated = narrate_rankings(rankings, fake)

    assert len(fake.calls) == len(rankings)
    for before, after in zip(rankings, narrated, strict=True):
        b, a = before.model_dump(), after.model_dump()
        # Ranks, scores, signal values, and contributors are byte-for-byte identical.
        assert a["rank"] == b["rank"]
        assert a["total_score"] == b["total_score"]
        assert a["reason"]["signals"] == b["reason"]["signals"]
        assert a["reason"]["data_points"] == b["reason"]["data_points"]
        # Only the summary changed.
        assert b["reason"]["summary"] == PENDING_SUMMARY
        assert (
            a["reason"]["summary"]
            == "Share is slipping in key accounts and a follow-up was missed."
        )
        a["reason"]["summary"] = b["reason"]["summary"]
        assert a == b


# ------------------------------------ priority-aware ranking narration (wording only)
class OfflineNarrator:
    """Deterministic offline narrator — the SAME priority-aware wording the demo uses."""

    def narrate(self, reason_input: dict, instruction: str) -> str:
        return offline_ranking_summary(reason_input)


def _narrated_d1(store):
    s, _ = store
    return narrate_rankings(rank_reps(_dm_ctx(), s), OfflineNarrator())


def test_no_gap_rep_is_not_called_the_priority(store):
    # A rep with NO triggered signal (score 0) gets the config no-gap summary and is never
    # described as "the priority" / urgent for a ride-along.
    zero = [r for r in _narrated_d1(store) if r.total_score == 0.0]
    assert zero, "seed (District 1) should include at least one zero-score, no-gap rep"
    for r in zero:
        assert r.reason.summary == RANKING_NO_GAP_SUMMARY
        text = r.reason.summary.lower()
        assert "the priority" not in text
        assert "priority for a ride-along" not in text


def test_high_score_rep_gets_high_priority_closing(store):
    settings = get_settings()
    high = [
        r for r in _narrated_d1(store) if r.total_score >= settings.ranking_high_priority_threshold
    ]
    assert high, "seed (District 1) should include a high-score rep"
    for r in high:
        assert r.reason.summary.startswith("This rep stands out on ")
        assert r.reason.summary.endswith(RANKING_HIGH_PRIORITY_CLOSING)


def test_low_but_nonzero_rep_gets_worth_attention_closing(store):
    settings = get_settings()
    low = [
        r
        for r in _narrated_d1(store)
        if 0.0 < r.total_score < settings.ranking_high_priority_threshold
    ]
    assert low, "seed (District 1) should include a low-but-nonzero rep"
    for r in low:
        assert r.reason.summary.startswith("This rep stands out on ")
        assert r.reason.summary.endswith(RANKING_LOW_PRIORITY_CLOSING)
        assert "the priority" not in r.reason.summary.lower()


def test_offline_priority_narration_changes_only_summary(store):
    # The new priority-aware narrator is still wording-only: ranks, scores, signal values, and
    # contributors are byte-for-byte unchanged (anti-LLM guard holds for the offline path too).
    s, _ = store
    before = rank_reps(_dm_ctx(), s)
    after = narrate_rankings(before, OfflineNarrator())
    for b_r, a_r in zip(before, after, strict=True):
        b, a = b_r.model_dump(), a_r.model_dump()
        assert a["rank"] == b["rank"]
        assert a["total_score"] == b["total_score"]
        assert a["reason"]["signals"] == b["reason"]["signals"]
        assert a["reason"]["data_points"] == b["reason"]["data_points"]
        assert b["reason"]["summary"] == PENDING_SUMMARY  # pre-narration placeholder
        assert a["reason"]["summary"] != PENDING_SUMMARY  # narrated
        a["reason"]["summary"] = b["reason"]["summary"]
        assert a == b
