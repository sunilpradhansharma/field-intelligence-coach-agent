"""T021 — example-based golden fixture for the deterministic ranking (seed 42, District 1).

Asserts the ranked order, the scores, and the reason structure match a committed golden.

IMPORTANT: this fixture is keyed on account/rep IDs and the Brand ENUM NAME (e.g.
`lupron_uro`), NOT on any brand DISPLAY spelling (e.g. "LUPRON URO" / "Litella"). The
"Litella" display spelling is still unconfirmed, so the scorer's data-point labels use the
stable enum name and this fixture deliberately never embeds a display spelling — that way an
unconfirmed/changed display spelling cannot break the golden. REVIEW this fixture once the
brand display spelling is confirmed.
"""

from coach.components.ranking import PENDING_SUMMARY, rank_reps
from coach.data_access.interface import AccessContext
from coach.data_access.sqlite_store import SqliteStore
from coach.schemas import Brand, Role
from coach.synthetic import generate

SEED = 42

# (rep_id, rank, total_score) for District 1 as a DM sees it. Ties (0.0) are broken by the
# documented rule: total desc, opportunity_risk desc, rep_id asc.
#
# NOTE: these scores changed (now in 0..1) due to signal NORMALIZATION — see
# docs/adr/0001-signal-normalization.md. Each signal is mapped to 0..1 via
# `Settings.ranking_norm_caps` before weighting, so the weights alone control influence.
# Normalization also reordered the two top reps (003 now edges 001), because 001's huge raw
# counts saturate at the cap while 003 scores higher across signals.
GOLDEN_D1 = [
    ("rep_d1_003", 1, 0.891667),
    ("rep_d1_001", 2, 0.833333),
    ("rep_d1_005", 3, 0.268858),
    ("rep_d1_006", 4, 0.260358),
    ("rep_d1_008", 5, 0.183033),
    ("rep_d1_002", 6, 0.0),
    ("rep_d1_004", 7, 0.0),
    ("rep_d1_007", 8, 0.0),
]

# Top rep's four signals: raw aggregate values and their normalized (0..1) values.
TOP_REP = "rep_d1_003"
TOP_SIGNALS_RAW = {
    "declining_share": 3.0476,
    "low_call_activity": 13.0,
    "missed_follow_up": 2.0,
    "opportunity_risk": 9.0,
}
TOP_SIGNALS_NORMALIZED = {
    "declining_share": 1.0,  # 3.0476 >= cap 3.0 -> saturates
    "low_call_activity": 1.0,  # 13 >= cap 10 -> saturates
    "missed_follow_up": 0.666667,  # 2 / cap 3
    "opportunity_risk": 0.9,  # 9 / cap 10
}


def _rank_d1():
    ds = generate(SEED)
    store = SqliteStore(":memory:")
    store.write_dataset(ds)
    ctx = AccessContext(
        user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
    )
    rankings = rank_reps(ctx, store)
    store.close()
    return rankings


def test_golden_ranked_order_and_scores():
    rankings = _rank_d1()
    assert [(r.rep_id, r.rank, r.total_score) for r in rankings] == GOLDEN_D1


def test_golden_top_rep_signal_values_and_structure():
    rankings = _rank_d1()
    top = next(r for r in rankings if r.rep_id == TOP_REP)
    assert top.rank == 1
    # Reason shows BOTH the raw aggregate and the normalized 0..1 value used in scoring.
    assert {sc.signal.value: sc.raw_value for sc in top.reason.signals} == TOP_SIGNALS_RAW
    assert {
        sc.signal.value: sc.normalized_value for sc in top.reason.signals
    } == TOP_SIGNALS_NORMALIZED
    # Contribution is exactly normalized * weight (pure code, no LLM); summary not yet narrated.
    for sc in top.reason.signals:
        assert sc.contribution == round(sc.normalized_value * sc.weight, 6)
    assert top.reason.summary == PENDING_SUMMARY
    assert top.reason.data_points  # has top contributors (raw (account, brand) rows)


def test_golden_reasons_are_independent_of_brand_display_spelling():
    # No data-point label may embed a brand DISPLAY spelling (e.g. "LUPRON URO"/"Litella");
    # labels use the stable enum name. This keeps the golden safe from the unconfirmed spelling.
    display_spellings = {b.value for b in Brand}
    for r in _rank_d1():
        for dp in r.reason.data_points:
            for spelling in display_spellings:
                assert spelling not in dp.label
