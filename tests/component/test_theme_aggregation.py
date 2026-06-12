"""Phase 7 / capability #6 — theme aggregation (P7-T1/T2/T3).

The two invariants are the point of this phase:
- PATTERNS / COUNTS ONLY — the aggregated output never exposes named individual reps or
  individually identifiable rep detail; it returns themes with counts/shares (FR-016).
- RBAC-SCOPED to leadership — only region / all may aggregate, each only across their own
  region / all; a DM (district) is rejected with `ScopeError`.

Plus: deterministic in code, themes from the SAME source as the per-rep coaching-focus section,
the anti-LLM guard (narration changes only `reason.summary`), and explainability (counts on
every theme). Uses a FakeLLM — no live Bedrock.
"""

import pytest

from coach.components.coaching_focus import coaching_focus_for_rep
from coach.components.theme_aggregation import aggregate_themes
from coach.config.settings import DEFAULT_FOCUS_AREA, get_settings
from coach.data_access.interface import AccessContext, ScopeError
from coach.data_access.sqlite_store import SqliteStore
from coach.llm.narrate import narrate_themes
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
    Theme,
    ThemeAggregate,
)
from coach.synthetic import generate

SEED = 42


class FakeLLM:
    """Deterministic stand-in for Claude — records calls, returns a fixed summary."""

    def __init__(self, text: str = "Synthetic narrated theme summary (patterns only)."):
        self.text = text
        self.calls: list[dict] = []

    def narrate(self, reason_input: dict, instruction: str) -> str:
        self.calls.append(reason_input)
        return self.text


def _region_ctx() -> AccessContext:
    return AccessContext(user_id="region_r1", role=Role.regional_director, region_id="R1")


def _all_ctx() -> AccessContext:
    return AccessContext(user_id="hos_1", role=Role.head_of_sales, region_id="R1")


def _dm_ctx() -> AccessContext:
    return AccessContext(
        user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
    )


def _self_ctx() -> AccessContext:
    return AccessContext(user_id="rep_d1_001", role=Role.rep, region_id="R1", rep_id="rep_d1_001")


@pytest.fixture
def store():
    s = SqliteStore(":memory:")
    s.write_dataset(generate(SEED))
    yield s
    s.close()


# ------------------------------------------------------------- deterministic golden (P7-T1)
# seed 42, region R1 (both districts). Ranked by count desc (no ties). (theme, signal, count, share)
GOLDEN_THEMES = [
    (
        "Pursue new therapy starts / under-served opportunity",
        SignalName.opportunity_risk,
        11,
        0.647059,
    ),
    (
        "Improve account prioritization and call planning",
        SignalName.low_call_activity,
        10,
        0.588235,
    ),
    ("Defend and regrow share at key accounts", SignalName.declining_share, 8, 0.470588),
    (DEFAULT_FOCUS_AREA, None, 5, 0.294118),
    ("Follow through on prior agreed coaching actions", SignalName.missed_follow_up, 2, 0.117647),
]


def test_golden_themes_counts_and_order(store):
    agg = aggregate_themes(_region_ctx(), store)
    assert agg.rep_count == 17
    assert agg.generated_for.scope == "R1"
    assert agg.generated_for.scope_level.value == "region"
    got = [(t.theme, t.signal, t.rep_count, t.rep_share) for t in agg.themes]
    assert got == GOLDEN_THEMES


def test_aggregation_is_deterministic(store):
    a = aggregate_themes(_region_ctx(), store).model_dump()
    b = aggregate_themes(_region_ctx(), store).model_dump()
    assert a == b


# ------------------------------------------------------- patterns / counts ONLY (P7-T1, FR-016)
def test_output_contains_no_rep_ids_or_names_structural(store):
    # Structural: neither Theme nor ThemeAggregate even has a rep-identity field.
    assert "rep_id" not in Theme.model_fields and "name" not in Theme.model_fields
    assert "rep_id" not in ThemeAggregate.model_fields


def test_output_exposes_no_individual_rep_detail(store):
    ds = generate(SEED)
    agg = aggregate_themes(_all_ctx(), store)
    blob = agg.model_dump_json()
    # No seeded rep id or rep name may appear anywhere in the serialized aggregate.
    for rep in ds.reps:
        assert rep.rep_id not in blob, f"leaked rep id {rep.rep_id}"
        assert rep.name not in blob, f"leaked rep name {rep.name}"
    # What it DOES carry is counts/shares only.
    for t in agg.themes:
        assert isinstance(t.rep_count, int) and 0.0 <= t.rep_share <= 1.0


# ------------------------------------------------------------- explainability (P7-T1, FR-010)
def test_every_theme_has_a_reason_with_counts(store):
    agg = aggregate_themes(_region_ctx(), store)
    assert agg.themes
    for t in agg.themes:
        assert t.reason.summary  # non-empty (pending placeholder pre-narration is non-empty)
        labels = {d.label: d.value for d in t.reason.data_points}
        assert labels["reps in scope"] == agg.rep_count
        assert labels["reps with this theme"] == t.rep_count
        assert "share of reps" in labels
        # supporting counts only — every data point comes from the aggregation, none names a rep.
        assert all(d.source == "theme_aggregation" for d in t.reason.data_points)


# --------------------------------------------------------------- same source as per-rep section
def test_themes_use_the_same_focus_catalog_as_the_per_rep_section(store):
    settings = get_settings()
    ctx = _region_ctx()
    # Independently tally each in-scope rep's coaching focuses (the per-rep section) ...
    expected: dict[str, int] = {}
    for rep in store.get_reps(ctx):
        for fa in {f.focus_area for f in coaching_focus_for_rep(ctx, store, rep.rep_id, settings)}:
            expected[fa] = expected.get(fa, 0) + 1
    # ... and assert the aggregation is exactly that roll-up (no second, drifting definition).
    agg = aggregate_themes(ctx, store)
    assert {t.theme: t.rep_count for t in agg.themes} == expected
    # Every theme label is a real catalog focus area (or the default) — never invented.
    catalog = set(settings.focus_catalog.values()) | {DEFAULT_FOCUS_AREA}
    assert all(t.theme in catalog for t in agg.themes)


# --------------------------------------------------------------------- RBAC scope (P7-T2)
def test_dm_and_rep_are_rejected_with_scope_error(store):
    # Aggregation is leadership-only; a district (DM) or self (rep) caller is rejected the SAME
    # way the rest of the layer rejects out-of-scope reads (a 403, indistinguishable from
    # not-found, over the API).
    with pytest.raises(ScopeError):
        aggregate_themes(_dm_ctx(), store)
    with pytest.raises(ScopeError):
        aggregate_themes(_self_ctx(), store)


def test_region_and_all_scopes_are_allowed(store):
    # Single-region seed: region and all both see all 17 reps.
    assert aggregate_themes(_region_ctx(), store).rep_count == 17
    all_agg = aggregate_themes(_all_ctx(), store)
    assert all_agg.rep_count == 17
    assert all_agg.generated_for.scope == "all"


# ------------------------------------------------------------- anti-LLM guard (P7-T3)
def test_narration_changes_only_summary(store):
    themes = aggregate_themes(_region_ctx(), store).themes
    fake = FakeLLM("Most reps in the region share a low-call-activity pattern.")
    narrated = narrate_themes(themes, fake)

    assert len(fake.calls) == len(themes)
    # The LLM was handed counts/shares only — never a rep identity.
    ds = generate(SEED)
    rep_ids = {r.rep_id for r in ds.reps}
    for call in fake.calls:
        import json

        assert not (rep_ids & set(json.dumps(call).split()))  # no rep id token in the LLM input

    for before, after in zip(themes, narrated, strict=True):
        b, a = before.model_dump(), after.model_dump()
        assert a["theme"] == b["theme"]
        assert a["signal"] == b["signal"]
        assert a["rep_count"] == b["rep_count"]
        assert a["rep_share"] == b["rep_share"]
        assert a["reason"]["data_points"] == b["reason"]["data_points"]  # counts unchanged
        assert (
            a["reason"]["summary"] == "Most reps in the region share a low-call-activity pattern."
        )
        a["reason"]["summary"] = b["reason"]["summary"]
        assert a == b  # only summary changed


# ---------------------------- region isolation + predictable counts (2-region dataset, P7-T2/T1)
def _rep_bundle(rep_id: str, district: str, declining: bool):
    trend = -0.6 if declining else 0.0  # share_drop 0.6 >= focus threshold 0.5 -> declining_share
    rep = Rep(rep_id=rep_id, name=f"Rep {rep_id}", district_id=district, tenure_months=12)
    acct = Account(
        account_id=f"a_{rep_id}",
        rep_id=rep_id,
        name=f"Acct {rep_id}",
        type=AccountType.account,
        market_share=0.2,
        share_trend=trend,
        volume=100.0,
        spend=100.0,
        performance=Performance.on,
        opportunity_level=OpportunityLevel.low,
        risk_flag=False,
        prp=False,
    )
    abm = AccountBrandMetrics(
        account_id=acct.account_id,
        brand=Brand.lupron_peds,
        market_share=0.2,
        share_trend=trend,
        volume=100.0,
        spend=100.0,
        performance=Performance.on,
        opportunity_level=OpportunityLevel.low,
        risk_flag=False,
    )
    call = CallActivity(
        activity_id=f"c_{rep_id}",
        rep_id=rep_id,
        account_id=acct.account_id,
        brand=Brand.lupron_peds,
        period="2026-05",
        calls=5,
        calls_trend=0.0,
    )
    return rep, acct, abm, call


def _two_region_dataset(b_declining: bool) -> Dataset:
    # R1: a declining, b declining iff b_declining. R2: a declining, b none.
    specs = [
        ("D1", "rep_r1_a", True),
        ("D1", "rep_r1_b", b_declining),
        ("D2", "rep_r2_a", True),
        ("D2", "rep_r2_b", False),
    ]
    reps, accts, abms, calls = [], [], [], []
    for district, rid, dec in specs:
        rep, a, m, c = _rep_bundle(rid, district, dec)
        reps.append(rep)
        accts.append(a)
        abms.append(m)
        calls.append(c)
    return Dataset(
        meta=GenerationMeta(seed=0, counts={}),
        regions=[Region(region_id="R1", name="R1"), Region(region_id="R2", name="R2")],
        districts=[
            District(district_id="D1", region_id="R1", name="D1"),
            District(district_id="D2", region_id="R2", name="D2"),
        ],
        users=[],
        reps=reps,
        accounts=accts,
        account_brand_metrics=abms,
        call_activity=calls,
        coaching_sessions=[],
    )


def test_region_caller_cannot_aggregate_another_region():
    store = SqliteStore(":memory:")
    store.write_dataset(_two_region_dataset(b_declining=False))
    declining = "Defend and regrow share at key accounts"

    r1 = aggregate_themes(
        AccessContext(user_id="x", role=Role.regional_director, region_id="R1"), store
    )
    r2 = aggregate_themes(
        AccessContext(user_id="y", role=Role.regional_director, region_id="R2"), store
    )
    counts_r1 = {t.theme: t.rep_count for t in r1.themes}
    counts_r2 = {t.theme: t.rep_count for t in r2.themes}
    assert r1.rep_count == 2 and r2.rep_count == 2  # each region sees only its own 2 reps
    assert counts_r1[declining] == 1 and counts_r1[DEFAULT_FOCUS_AREA] == 1
    assert counts_r2[declining] == 1 and counts_r2[DEFAULT_FOCUS_AREA] == 1

    # "all" sees both regions (4 reps; declining across both).
    all_agg = aggregate_themes(
        AccessContext(user_id="h", role=Role.head_of_sales, region_id="R1"), store
    )
    assert all_agg.rep_count == 4
    assert {t.theme: t.rep_count for t in all_agg.themes}[declining] == 2
    store.close()


def test_changing_the_data_changes_counts_predictably():
    # Flip rep_r1_b to declining too -> R1's declining count 1 -> 2, default 1 -> 0.
    store = SqliteStore(":memory:")
    store.write_dataset(_two_region_dataset(b_declining=True))
    declining = "Defend and regrow share at key accounts"
    r1 = aggregate_themes(
        AccessContext(user_id="x", role=Role.regional_director, region_id="R1"), store
    )
    counts = {t.theme: t.rep_count for t in r1.themes}
    assert counts[declining] == 2
    assert DEFAULT_FOCUS_AREA not in counts  # no rep left without a triggered theme
    store.close()
