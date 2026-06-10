"""T032 — accounts / business-context component tests.

- Focused, deterministic selection (seed 42): expected key (account, brand) rows + order; the
  config cap is respected; the list is a focused subset, not the whole book.
- Per-brand labeling (FR-007 / finding N2): one AccountFocus per (account, brand), labeled by
  the Brand display name (LILETTA renders); no per-account collapsing.
- Mismatch flag (FR-008): high opportunity + low calls flagged with a reason; a well-served
  one not flagged; the config threshold changes the flag predictably.
- RBAC + PRP: reads only through the data layer, so out-of-scope -> ScopeError and PRP HCPs
  never appear.
- Explainability (FR-010): every AccountFocus has a non-empty structured reason with data.
- Anti-LLM guard: narration changes ONLY reason.summary.
- Edge cases (FR-018): no-accounts -> empty; missing call activity -> "not recorded".
"""

from dataclasses import replace

import pytest

from coach.components.accounts_context import PENDING_SUMMARY, accounts_context_for_rep
from coach.config.settings import get_settings
from coach.data_access.interface import AccessContext, ScopeError
from coach.data_access.sqlite_store import SqliteStore
from coach.schemas import Brand, OpportunityLevel, Role
from coach.synthetic import generate

SEED = 42


class FakeLLM:
    def __init__(self, text: str = "Synthetic narrated account reason."):
        self.text = text
        self.calls: list[dict] = []

    def narrate(self, reason_input: dict, instruction: str) -> str:
        self.calls.append(reason_input)
        return self.text


def _dm_ctx():
    return AccessContext(
        user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
    )


def _all_ctx():
    return AccessContext(user_id="hos_1", role=Role.head_of_sales, region_id="R1")


def _build(ds=None):
    ds = ds or generate(SEED)
    store = SqliteStore(":memory:")
    store.write_dataset(ds)
    return store, ds


@pytest.fixture
def env():
    store, ds = _build()
    yield store, ds
    store.close()


# ------------------------------------------------ focused, deterministic selection
EXPECTED_D1_001 = [
    ("acct_rep_d1_001_03", "LILETTA"),
    ("acct_rep_d1_001_19", "LUPRON GYN"),
    ("acct_rep_d1_001_13", "LUPRON GYN"),
    ("acct_rep_d1_001_06", "LUPRON URO"),
    ("acct_rep_d1_001_20", "LUPRON GYN"),
]


def test_focused_key_accounts_example(env):
    store, _ = env
    settings = get_settings()
    total = len(store.get_account_brand_metrics(_dm_ctx(), "rep_d1_001"))
    out = accounts_context_for_rep(_dm_ctx(), store, "rep_d1_001")
    assert len(out) == settings.accounts_max  # capped
    assert len(out) < total  # focused, not the whole book
    assert [(f.account_id, f.brand.value) for f in out] == EXPECTED_D1_001


# ----------------------------------------------------- per-brand labeling (FR-007/N2)
def test_one_focus_per_account_brand_labeled_by_display_name(env):
    store, _ = env
    big = replace(get_settings(), accounts_max=10_000)
    out = accounts_context_for_rep(_dm_ctx(), store, "rep_d1_001", big)
    metrics = store.get_account_brand_metrics(_dm_ctx(), "rep_d1_001")
    # One AccountFocus per (account, brand) — no per-account collapsing.
    assert sorted((f.account_id, f.brand.name) for f in out) == sorted(
        (m.account_id, m.brand.name) for m in metrics
    )
    # An account carrying multiple brands yields multiple AccountFocus rows.
    acct_02 = [f for f in out if f.account_id == "acct_rep_d1_001_02"]
    assert len({f.brand for f in acct_02}) > 1
    # The Brand display name is surfaced (LILETTA renders correctly).
    liletta = [f for f in out if f.brand == Brand.liletta]
    assert liletta and all(f.brand.value == "LILETTA" for f in liletta)


# --------------------------------------------------------------- mismatch flag (FR-008)
def test_high_opportunity_low_calls_is_flagged_with_reason(env):
    store, _ = env
    out = accounts_context_for_rep(_dm_ctx(), store, "rep_d1_001")
    flagged = [f for f in out if f.mismatch_flag]
    assert flagged  # rep_d1_001's key accounts are high-opp with low calls
    for f in flagged:
        assert f.context.opportunity_level == OpportunityLevel.high
        assert any("mismatch" in dp.label for dp in f.reason.data_points)


def test_well_served_account_is_not_flagged(env):
    store, _ = env
    # rep_d1_002's high-opportunity accounts have healthy call activity (> threshold).
    out = accounts_context_for_rep(_dm_ctx(), store, "rep_d1_002")
    well_served = [
        f
        for f in out
        if f.context.opportunity_level == OpportunityLevel.high
        and f.context.calls > get_settings().mismatch_call_threshold
    ]
    assert well_served and all(not f.mismatch_flag for f in well_served)


def test_changing_mismatch_threshold_changes_the_flag(env):
    store, _ = env
    big = replace(get_settings(), accounts_max=10_000)
    out = accounts_context_for_rep(_dm_ctx(), store, "rep_d1_005", big)
    # A high-opportunity row sitting exactly at the default threshold (calls == 2).
    boundary = next(
        f
        for f in out
        if f.context.opportunity_level == OpportunityLevel.high and f.context.calls == 2
    )
    assert boundary.mismatch_flag is True  # default threshold = 2 -> 2 <= 2
    tightened = replace(big, mismatch_call_threshold=1)
    out2 = accounts_context_for_rep(_dm_ctx(), store, "rep_d1_005", tightened)
    same = next(
        f for f in out2 if f.account_id == boundary.account_id and f.brand == boundary.brand
    )
    assert same.mismatch_flag is False  # 2 <= 1 is False


# ----------------------------------------------------------------------- RBAC + PRP
def test_out_of_scope_rep_raises_scope_error(env):
    store, ds = env
    d2_rep = next(rp.rep_id for rp in ds.reps if rp.district_id == "D2")
    with pytest.raises(ScopeError):
        accounts_context_for_rep(_dm_ctx(), store, d2_rep)


def test_prp_accounts_never_appear(env):
    store, ds = env
    prp_ids = {a.account_id for a in ds.accounts if a.prp}
    assert prp_ids  # guard: PRP accounts exist in the seed
    big = replace(get_settings(), accounts_max=10_000)
    for rep in {a.rep_id for a in ds.accounts}:
        out = accounts_context_for_rep(_all_ctx(), store, rep, big)
        assert prp_ids.isdisjoint({f.account_id for f in out})


# ------------------------------------------------------------- explainability (FR-010)
def test_every_focus_has_structured_reason(env):
    store, _ = env
    out = accounts_context_for_rep(_dm_ctx(), store, "rep_d1_001")
    for f in out:
        assert f.reason.summary  # non-empty
        assert f.reason.data_points  # the real per-(account, brand) numbers


# -------------------------------------------------------------------- anti-LLM guard
def test_narration_changes_only_summary(env):
    from coach.llm.narrate import narrate_account_focuses

    store, _ = env
    out = accounts_context_for_rep(_dm_ctx(), store, "rep_d1_001")
    fake = FakeLLM("Share is slipping on LILETTA at a high-opportunity account; calls are low.")
    narrated = narrate_account_focuses(out, fake)

    assert len(fake.calls) == len(out)
    for before, after in zip(out, narrated, strict=True):
        b, a = before.model_dump(), after.model_dump()
        assert a["account_id"] == b["account_id"]
        assert a["brand"] == b["brand"]
        assert a["context"] == b["context"]
        assert a["mismatch_flag"] == b["mismatch_flag"]
        assert a["reason"]["data_points"] == b["reason"]["data_points"]
        assert b["reason"]["summary"] == PENDING_SUMMARY
        assert a["reason"]["summary"] == fake.text
        a["reason"]["summary"] = b["reason"]["summary"]
        assert a == b


# ------------------------------------------------------------ edge cases (FR-018)
def test_no_accounts_returns_empty_list():
    ds = generate(SEED)
    # Drop rep_d1_001's per-brand metrics -> no (account, brand) rows to surface.
    ds.account_brand_metrics = [
        m for m in ds.account_brand_metrics if "rep_d1_001" not in m.account_id
    ]
    store, _ = _build(ds)
    assert accounts_context_for_rep(_dm_ctx(), store, "rep_d1_001") == []
    store.close()


def test_missing_call_activity_marked_not_recorded():
    ds = generate(SEED)
    # Remove one (account, brand)'s call activity to exercise the missing-data path.
    target = next(c for c in ds.call_activity if "rep_d1_001" in c.account_id)
    ds.call_activity = [
        c
        for c in ds.call_activity
        if not (c.account_id == target.account_id and c.brand == target.brand)
    ]
    store, _ = _build(ds)
    big = replace(get_settings(), accounts_max=10_000)
    out = accounts_context_for_rep(_dm_ctx(), store, "rep_d1_001", big)
    focus = next(f for f in out if f.account_id == target.account_id and f.brand == target.brand)
    assert focus.context.calls == 0  # not fabricated
    assert any("not recorded" in dp.label for dp in focus.reason.data_points)
    store.close()
