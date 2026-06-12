"""Phase 8 / capability #5 — Summit optimization (P8-T1, P8-T2).

Covers: deterministic Summit math + what-if lift; the per-team config formula is config-driven
(not hard-coded); integration into the EXISTING normalized rollup (weighted from config, off by
default); explainability; the anti-LLM guard (narration changes only wording); and RBAC + PRP
(reads only through the data-access layer; PRP rows scrubbed). FakeLLM — no live Bedrock.

The datasets set market_share / volume / calls to 0, so a district's Summit score is just
`-decline_penalty x total_share_decline` — which makes the math easy to assert exactly.
"""

from dataclasses import replace

from coach.components.ranking import rank_reps
from coach.components.summit import district_summit_scores, summit_insight_for_rep
from coach.config.settings import SummitFormula, get_settings
from coach.data_access.interface import AccessContext
from coach.data_access.sqlite_store import SqliteStore
from coach.llm.narrate import narrate_summit
from coach.schemas import (
    Account,
    AccountBrandMetrics,
    AccountType,
    Brand,
    CallActivity,
    Dataset,
    District,
    GenerationMeta,
    OpportunityLevel,
    Performance,
    Region,
    Rep,
    Role,
    SignalName,
)


def _hos_ctx() -> AccessContext:
    return AccessContext(user_id="hos_1", role=Role.head_of_sales, region_id="R1")


def _row(rep_id: str, n: int, trend: float, prp: bool = False):
    """One (account, brand) row (share/volume/calls = 0 so only the decline term matters)."""
    aid = f"a_{rep_id}_{n}"
    acct = Account(
        account_id=aid,
        rep_id=rep_id,
        name=f"Acct {aid}",
        type=AccountType.account,
        market_share=0.0,
        share_trend=trend,
        volume=0.0,
        spend=0.0,
        performance=Performance.on,
        opportunity_level=OpportunityLevel.low,
        risk_flag=False,
        prp=prp,
    )
    abm = AccountBrandMetrics(
        account_id=aid,
        brand=Brand.lupron_peds,
        market_share=0.0,
        share_trend=trend,
        volume=0.0,
        spend=0.0,
        performance=Performance.on,
        opportunity_level=OpportunityLevel.low,
        risk_flag=False,
    )
    call = CallActivity(
        activity_id=f"c_{aid}",
        rep_id=rep_id,
        account_id=aid,
        brand=Brand.lupron_peds,
        period="2026-05",
        calls=0,
        calls_trend=0.0,
    )
    return acct, abm, call


def _make_ds(reps_spec) -> Dataset:
    """reps_spec: list of (district_id, rep_id, [(n, trend, prp?), ...])."""
    district_ids = sorted({d for d, _, _ in reps_spec})
    reps, accts, abms, calls = [], [], [], []
    for d, rid, rows in reps_spec:
        reps.append(Rep(rep_id=rid, name=f"Rep {rid}", district_id=d, tenure_months=12))
        for spec in rows:
            acct, abm, call = _row(rid, *spec)
            accts.append(acct)
            abms.append(abm)
            calls.append(call)
    return Dataset(
        meta=GenerationMeta(seed=0, counts={}),
        regions=[Region(region_id="R1", name="R1")],
        districts=[District(district_id=d, region_id="R1", name=d) for d in district_ids],
        users=[],
        reps=reps,
        accounts=accts,
        account_brand_metrics=abms,
        call_activity=calls,
        coaching_sessions=[],
    )


# Three districts, decreasing decline -> scores A=-20, B=-12, C=-4 (default penalty 40).
_THREE = [
    ("A", "a1", [(1, -0.5)]),
    ("B", "b1", [(1, -0.3)]),
    ("C", "c1", [(1, -0.1)]),
]


def _store(reps_spec) -> SqliteStore:
    s = SqliteStore(":memory:")
    s.write_dataset(_make_ds(reps_spec))
    return s


# -------------------------------------------------- deterministic math + what-if lift (P8-T1)
def test_deterministic_scores_and_whatif_lift():
    store = _store(_THREE)
    assert district_summit_scores(_hos_ctx(), store) == {"A": -20.0, "B": -12.0, "C": -4.0}
    # A is last (#3); halting its rep's 0.5 decline -> score 0 -> #1. Lift = 2 ("#3 -> #1").
    a = summit_insight_for_rep(_hos_ctx(), store, "a1")
    assert (a.baseline_position, a.projected_position, a.lift) == (3, 1, 2)
    assert a.team_formula == "default"
    b = summit_insight_for_rep(_hos_ctx(), store, "b1")
    assert (b.baseline_position, b.projected_position, b.lift) == (2, 1, 1)
    c = summit_insight_for_rep(_hos_ctx(), store, "c1")
    assert (c.baseline_position, c.projected_position, c.lift) == (1, 1, 0)
    store.close()


def test_summit_is_deterministic():
    store = _store(_THREE)
    a = summit_insight_for_rep(_hos_ctx(), store, "a1").model_dump()
    b = summit_insight_for_rep(_hos_ctx(), store, "a1").model_dump()
    assert a == b
    store.close()


# ------------------------------------------------------- per-team config-driven (P8-T1/T2)
def test_per_team_config_formula_changes_results():
    # Two IDENTICAL districts; only the configured per-team formula differs -> different scores.
    store = _store([("X", "x1", [(1, -0.3)]), ("Y", "y1", [(1, -0.3)])])
    settings = replace(
        get_settings(),
        summit_formulas={"default": SummitFormula(), "Y": SummitFormula(decline_penalty=200.0)},
    )
    scores = district_summit_scores(_hos_ctx(), store, settings)
    assert scores["X"] == round(-40.0 * 0.3, 6)  # default penalty 40
    assert scores["Y"] == round(-200.0 * 0.3, 6)  # team Y's configured penalty 200
    assert scores["X"] != scores["Y"]  # same inputs, config-driven difference (not hard-coded)
    store.close()


def test_changing_the_formula_changes_scores_predictably():
    store = _store(_THREE)
    base = district_summit_scores(_hos_ctx(), store)  # default penalty 40
    doubled = district_summit_scores(
        _hos_ctx(),
        store,
        replace(get_settings(), summit_formulas={"default": SummitFormula(decline_penalty=80.0)}),
    )
    for d in base:
        assert doubled[d] == round(base[d] * 2, 6)  # only the decline term -> doubles predictably
    store.close()


# ------------------------------------------ integration into the normalized rollup (P8-T1)
def test_summit_is_off_by_default_and_folds_in_when_weighted():
    store = _store(_THREE)
    hos = _hos_ctx()

    # Default config (weight 0.0): NO Summit signal, the four-signal scores are unchanged.
    off = {r.rep_id: r for r in rank_reps(hos, store)}
    for r in off.values():
        assert SignalName.summit_opportunity not in {sc.signal for sc in r.reason.signals}

    # Non-zero Summit weight: folded into the SAME normalized rollup.
    base_settings = get_settings()
    on_settings = replace(
        base_settings,
        ranking_weights={**base_settings.ranking_weights, "summit_opportunity": 1.0},
    )
    on = {r.rep_id: r for r in rank_reps(hos, store, on_settings)}
    a = on["a1"]
    summit = next(sc for sc in a.reason.signals if sc.signal == SignalName.summit_opportunity)
    cap = on_settings.ranking_norm_caps["summit_opportunity"]  # 3
    assert summit.raw_value == 2.0  # the lift
    assert summit.normalized_value == round(2.0 / cap, 6)  # normalized 0..1 (ADR 0001)
    assert summit.weight == 1.0
    assert summit.contribution == round(round(2.0 / cap, 6) * 1.0, 6)
    # The score is the four-signal score PLUS the normalized Summit contribution (no bypass).
    assert a.total_score == round(off["a1"].total_score + summit.contribution, 6)
    store.close()


# ------------------------------------------------------------- explainability (P8-T1, FR-010)
def test_every_insight_has_a_reason_with_lift_and_targets():
    store = _store(_THREE)
    a = summit_insight_for_rep(_hos_ctx(), store, "a1")
    assert a.reason.summary  # non-empty (pending placeholder pre-narration)
    labels = {d.label: d.value for d in a.reason.data_points}
    assert labels["ranking lift (positions gained)"] == 2
    assert any("Summit position" in lbl for lbl in labels)
    assert a.targets and all(t.decline_reduced > 0 for t in a.targets)
    # every target carries the raw movement (current trend -> projected 0.0)
    assert all(t.share_trend < 0 and t.projected_share_trend == 0.0 for t in a.targets)
    store.close()


# ------------------------------------------------------------- anti-LLM guard (P8-T2)
class FakeLLM:
    def __init__(self):
        self.calls: list[dict] = []

    def narrate(self, reason_input: dict, instruction: str) -> str:
        self.calls.append(reason_input)
        return "Focus on the top declining accounts to move the district up."


def test_narration_changes_only_summary():
    store = _store(_THREE)
    insight = summit_insight_for_rep(_hos_ctx(), store, "a1")
    fake = FakeLLM()
    narrated = narrate_summit(insight, fake)

    assert len(fake.calls) == 1
    b, n = insight.model_dump(), narrated.model_dump()
    assert n["lift"] == b["lift"]
    assert n["baseline_position"] == b["baseline_position"]
    assert n["projected_position"] == b["projected_position"]
    assert n["targets"] == b["targets"]
    assert n["reason"]["data_points"] == b["reason"]["data_points"]  # numbers preserved
    assert n["reason"]["summary"] == "Focus on the top declining accounts to move the district up."
    n["reason"]["summary"] = b["reason"]["summary"]
    assert n == b  # only the summary changed
    store.close()


# ------------------------------------------------------------- RBAC + PRP (P8-T1)
def test_prp_rows_are_scrubbed_and_never_appear():
    # A rep with a normal declining row + a PRP declining row; PRP is scrubbed at the data layer.
    store = _store([("A", "a1", [(1, -0.4, False), (2, -0.9, True)])])
    ins = summit_insight_for_rep(_hos_ctx(), store, "a1")
    target_accts = {t.account_id for t in ins.targets}
    assert "a_a1_2" not in target_accts  # the PRP account never surfaces
    assert "a_a1_1" in target_accts
    # The district score reflects only the non-PRP decline (0.4), not the scrubbed 0.9.
    assert district_summit_scores(_hos_ctx(), store)["A"] == round(-40.0 * 0.4, 6)
    store.close()


def test_summit_is_rbac_scoped_through_the_data_layer():
    # A DM sees only their own district, so Summit aggregates that district alone.
    store = _store(_THREE)
    dm = AccessContext(user_id="dm", role=Role.district_manager, region_id="R1", district_id="A")
    scores = district_summit_scores(dm, store)
    assert set(scores) == {"A"}  # only the in-scope district (B, C never read)
    store.close()


# ------------------------------- recovery_fraction: a tunable, config-driven modeling assumption
def _recovery_settings(value: float):
    return replace(
        get_settings(), summit_formulas={"default": SummitFormula(recovery_fraction=value)}
    )


def test_recovery_fraction_changes_the_lift_predictably():
    # Same inputs (a1's 0.5 decline); only the configured recovery_fraction changes. A smaller
    # recovery removes less decline -> a smaller score rise -> a smaller (or equal) lift.
    store = _store(_THREE)
    hos = _hos_ctx()
    lift_full = summit_insight_for_rep(hos, store, "a1", _recovery_settings(1.0)).lift
    lift_half = summit_insight_for_rep(hos, store, "a1", _recovery_settings(0.5)).lift
    lift_none = summit_insight_for_rep(hos, store, "a1", _recovery_settings(0.0)).lift
    assert (lift_full, lift_half, lift_none) == (2, 1, 0)  # halving recovery halves this lift

    # The per-target projection also scales with the recovery (deterministic, in code).
    half = summit_insight_for_rep(hos, store, "a1", _recovery_settings(0.5))
    t = half.targets[0]
    assert t.decline_reduced == round(0.5 * 0.5, 6)  # half of the 0.5 decline
    assert t.projected_share_trend == round(-0.5 * (1.0 - 0.5), 6)  # half the decline remains
    store.close()


def test_default_recovery_is_full_and_unchanged():
    # The default is 1.0 (full recovery), so the prior Phase 8 behavior is unchanged.
    assert get_settings().summit_formulas["default"].recovery_fraction == 1.0
    store = _store(_THREE)
    a = summit_insight_for_rep(_hos_ctx(), store, "a1")  # default settings
    assert a.lift == 2 and a.targets[0].decline_reduced == 0.5
    assert a.targets[0].projected_share_trend == 0.0  # full halt
    store.close()


def test_two_teams_with_different_recovery_produce_different_lifts():
    # Districts X and Y have IDENTICAL inputs; only their configured recovery_fraction differs.
    store = _store([("X", "x1", [(1, -0.5)]), ("Y", "y1", [(1, -0.5)]), ("Z", "z1", [(1, -0.45)])])
    settings = replace(
        get_settings(),
        summit_formulas={
            "default": SummitFormula(),
            "X": SummitFormula(recovery_fraction=1.0),
            "Y": SummitFormula(recovery_fraction=0.5),
        },
    )
    x = summit_insight_for_rep(_hos_ctx(), store, "x1", settings)
    y = summit_insight_for_rep(_hos_ctx(), store, "y1", settings)
    # Same inputs, different configured recovery -> different Summit projections AND lifts.
    assert x.team_formula == "X" and y.team_formula == "Y"
    assert x.targets[0].decline_reduced == 0.5 and y.targets[0].decline_reduced == 0.25
    assert x.lift != y.lift  # config-driven, not hard-coded
    store.close()
