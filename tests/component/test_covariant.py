"""Phase 9 / capability #4 — covariant analysis (P9-T1, P9-T2, P9-T3).

Covers: deterministic + transparent findings (an exact golden on the seed); the config-driven
success measure (changing it changes the findings predictably); insufficient-data honesty (a thin
slice returns a clear state, no fabricated association); explainability (a reason with the
variables, the success measure, and the supporting numbers); the anti-LLM guard (narration changes
only wording); and RBAC + PRP (reads only through the data-access layer; PRP rows scrubbed,
out-of-scope data never read). FakeLLM — no live Bedrock.
"""

from dataclasses import replace

from coach.components.covariant import covariant_analysis, meets_success_measure
from coach.config.settings import SuccessMeasure, get_settings
from coach.data_access.interface import AccessContext
from coach.data_access.sqlite_store import SqliteStore
from coach.llm.narrate import narrate_covariant
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
)
from coach.synthetic import generate

SEED = 42


def _dm_ctx() -> AccessContext:
    return AccessContext(
        user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
    )


def _hos_ctx() -> AccessContext:
    return AccessContext(user_id="hos_1", role=Role.head_of_sales, region_id="R1")


def _seed_store() -> SqliteStore:
    s = SqliteStore(":memory:")
    s.write_dataset(generate(SEED))
    return s


# --------------------------------------------------- deterministic + transparent golden (P9-T2)
def test_golden_findings_on_the_seed():
    store = _seed_store()
    a = covariant_analysis(_dm_ctx(), store)  # District 1, default success measure
    assert a.insufficient_data is False
    assert a.success_measure == "rising share (share_trend > 0.0) and performance on/above target"
    assert a.rows_analyzed == 299
    assert a.success_rate_overall == 0.521739

    by_var = {f.variable: f for f in a.variable_findings}
    ca = by_var["call_activity"]
    assert (ca.n_high, ca.success_rate_high) == (212, 0.70283)
    assert (ca.n_low, ca.success_rate_low) == (87, 0.08046)
    assert ca.lift == 0.62237  # high call activity strongly associates with success
    ss = by_var["spend_support"]
    assert (ss.n_high, ss.success_rate_high, ss.n_low, ss.success_rate_low) == (
        154,
        0.571429,
        145,
        0.468966,
    )

    # The optimal blend is a plain, inspectable max over combinations (not a black box).
    assert a.optimal_blend is not None
    assert a.optimal_blend.variables == ["call_activity", "spend_support"]
    assert (a.optimal_blend.n, a.optimal_blend.success_rate) == (115, 0.730435)
    store.close()


def test_analysis_is_deterministic():
    store = _seed_store()
    assert (
        covariant_analysis(_dm_ctx(), store).model_dump()
        == covariant_analysis(_dm_ctx(), store).model_dump()
    )
    store.close()


# ------------------------------------------------------- config-driven success measure (P9-T1)
def test_changing_the_success_measure_changes_findings_predictably():
    store = _seed_store()
    default = covariant_analysis(_dm_ctx(), store)
    # Relax the measure: drop the on/above-target requirement -> a SUPERSET of successes.
    relaxed_settings = replace(
        get_settings(),
        success_measure=SuccessMeasure(min_share_trend=0.0, require_on_or_above_target=False),
    )
    relaxed = covariant_analysis(_dm_ctx(), store, relaxed_settings)

    assert relaxed.rows_analyzed == default.rows_analyzed  # same rows, different measure
    assert (
        relaxed.success_measure != default.success_measure
    )  # the measure is config-driven, visible
    assert relaxed.success_rate_overall > default.success_rate_overall  # relaxation -> more wins
    store.close()


def test_meets_success_measure_is_the_single_visible_definition():
    rising_on = AccountBrandMetrics(
        account_id="a",
        brand=Brand.lupron_peds,
        market_share=0.2,
        share_trend=0.05,
        volume=1.0,
        spend=1.0,
        performance=Performance.on,
        opportunity_level=OpportunityLevel.med,
        risk_flag=False,
    )
    falling = rising_on.model_copy(update={"share_trend": -0.05})
    rising_under = rising_on.model_copy(update={"performance": Performance.under})
    default = get_settings().success_measure
    assert meets_success_measure(rising_on, default) is True
    assert meets_success_measure(falling, default) is False  # not rising
    assert meets_success_measure(rising_under, default) is False  # rising but not on/above target
    # Config relaxation flips the on/above-target gate.
    relaxed = SuccessMeasure(require_on_or_above_target=False)
    assert meets_success_measure(rising_under, relaxed) is True


# ------------------------------------------------------------- explainability (P9-T2, FR-010)
def test_reason_carries_the_variables_measure_and_numbers():
    store = _seed_store()
    a = covariant_analysis(_dm_ctx(), store)
    labels = {d.label: d.value for d in a.reason.data_points}
    assert labels["success measure"] == a.success_measure
    assert labels["(account, brand) rows analyzed"] == a.rows_analyzed
    assert labels["overall success rate"] == a.success_rate_overall
    assert "call_activity: success rate high vs low" in labels
    assert "optimal blend" in labels
    # Honesty stated in the output, not just comments.
    assert "synthetic data" in labels["note"]
    store.close()


# --------------------------- custom dataset (PRP scrub, RBAC scope, insufficient data) ---------
def _row(
    rep_id: str,
    n: int,
    share_trend: float,
    performance: Performance,
    spend: float,
    calls: int,
    prp: bool = False,
):
    aid = f"a_{rep_id}_{n}"
    acct = Account(
        account_id=aid,
        rep_id=rep_id,
        name=aid,
        type=AccountType.account,
        market_share=0.2,
        share_trend=share_trend,
        volume=1000.0,
        spend=spend,
        performance=performance,
        opportunity_level=OpportunityLevel.med,
        risk_flag=False,
        prp=prp,
    )
    abm = AccountBrandMetrics(
        account_id=aid,
        brand=Brand.lupron_peds,
        market_share=0.2,
        share_trend=share_trend,
        volume=1000.0,
        spend=spend,
        performance=performance,
        opportunity_level=OpportunityLevel.med,
        risk_flag=False,
    )
    call = CallActivity(
        activity_id=f"c_{aid}",
        rep_id=rep_id,
        account_id=aid,
        brand=Brand.lupron_peds,
        period="p",
        calls=calls,
        calls_trend=0.0,
    )
    return acct, abm, call


def _make_ds(reps_spec) -> Dataset:
    """reps_spec: list of (district, rep_id, [row tuples])."""
    district_ids = sorted({d for d, _, _ in reps_spec})
    reps, accts, abms, calls = [], [], [], []
    for d, rid, rows in reps_spec:
        reps.append(Rep(rep_id=rid, name=rid, district_id=d, tenure_months=12))
        for spec in rows:
            ac, ab, ca = _row(rid, *spec)
            accts.append(ac)
            abms.append(ab)
            calls.append(ca)
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


def test_insufficient_data_is_honest_not_fabricated():
    # Only 3 (account, brand) rows -> below the default min_rows (8) -> a clear insufficient state.
    store = SqliteStore(":memory:")
    store.write_dataset(
        _make_ds(
            [
                (
                    "D1",
                    "r1",
                    [
                        (1, 0.05, Performance.on, 5000.0, 5),
                        (2, -0.1, Performance.under, 1000.0, 0),
                        (3, 0.02, Performance.on, 4000.0, 4),
                    ],
                )
            ]
        )
    )
    a = covariant_analysis(_dm_ctx(), store)
    assert a.insufficient_data is True
    assert a.optimal_blend is None
    assert a.variable_findings == []  # no association claimed
    assert any("insufficient data" in d.label for d in a.reason.data_points)
    store.close()


def test_prp_rows_are_scrubbed_and_never_counted():
    # 4 non-PRP rows + 1 PRP row; with min_rows/min_support lowered so the analysis runs.
    store = SqliteStore(":memory:")
    store.write_dataset(
        _make_ds(
            [
                (
                    "D1",
                    "r1",
                    [
                        (1, 0.05, Performance.on, 5000.0, 5),
                        (2, -0.1, Performance.under, 1000.0, 0),
                        (3, 0.03, Performance.on, 4500.0, 6),
                        (4, -0.02, Performance.under, 1500.0, 1),
                        (9, 0.20, Performance.over, 8000.0, 9, True),  # PRP — must be scrubbed
                    ],
                )
            ]
        )
    )
    settings = replace(get_settings(), covariant_min_rows=1, covariant_min_support=1)
    a = covariant_analysis(_dm_ctx(), store, settings)
    assert a.rows_analyzed == 4  # the PRP row never enters the analysis
    store.close()


def test_analysis_is_rbac_scoped_through_the_data_layer():
    store = _seed_store()
    dm_rows = covariant_analysis(_dm_ctx(), store).rows_analyzed
    all_rows = covariant_analysis(_hos_ctx(), store).rows_analyzed
    assert dm_rows == 299  # District 1 only
    assert all_rows > dm_rows  # "all" scope reads more rows (both districts) — scoping bites
    store.close()


# ------------------------------------------------------------- anti-LLM guard (P9-T3)
class FakeLLM:
    def __init__(self):
        self.calls: list[dict] = []

    def narrate(self, reason_input: dict, instruction: str) -> str:
        self.calls.append(reason_input)
        return "Reps who keep call activity up while backing accounts with spend win more often."


def test_narration_changes_only_summary():
    store = _seed_store()
    a = covariant_analysis(_dm_ctx(), store)
    fake = FakeLLM()
    narrated = narrate_covariant(a, fake)

    assert len(fake.calls) == 1
    b, n = a.model_dump(), narrated.model_dump()
    assert n["variable_findings"] == b["variable_findings"]
    assert n["optimal_blend"] == b["optimal_blend"]
    assert n["success_measure"] == b["success_measure"]
    assert n["rows_analyzed"] == b["rows_analyzed"]
    assert n["success_rate_overall"] == b["success_rate_overall"]
    assert n["reason"]["data_points"] == b["reason"]["data_points"]  # numbers preserved
    assert (
        n["reason"]["summary"]
        == "Reps who keep call activity up while backing accounts with spend win more often."
    )
    n["reason"]["summary"] = b["reason"]["summary"]
    assert n == b  # only the summary changed
    store.close()
