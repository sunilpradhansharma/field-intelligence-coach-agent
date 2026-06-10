"""T018 — data-access + seeded generator tests.

Covers: required shape/counts, signal variety with edge cases, determinism (same seed →
identical data), synthetic-only provenance, and a store round-trip through the interface.
"""

from collections import Counter

from coach.config.settings import SIGNALS
from coach.data_access.interface import AccessContext
from coach.data_access.sqlite_store import SqliteStore
from coach.schemas import AccountType, Brand, Role

SEED = 42


# ----------------------------------------------------------------- determinism
def test_generation_is_deterministic_for_same_seed():
    from coach.synthetic import generate

    a = generate(SEED)
    b = generate(SEED)
    assert a.model_dump() == b.model_dump()


def test_different_seed_produces_different_data():
    from coach.synthetic import generate

    assert generate(SEED).model_dump() != generate(SEED + 1).model_dump()


# ----------------------------------------------------------------------- shape
def test_top_level_shape():
    from coach.synthetic import generate

    ds = generate(SEED)
    assert len(ds.regions) == 1
    assert len(ds.districts) == 2
    assert {d.district_id for d in ds.districts} == {"D1", "D2"}
    # 2 DMs (district) + 1 RD (region) + 1 Head of Sales (all); both districts in one region.
    roles = Counter(u.role for u in ds.users)
    assert roles[Role.district_manager] == 2
    assert roles[Role.regional_director] == 1
    assert roles[Role.head_of_sales] == 1
    assert len(ds.users) == 4
    assert all(d.region_id == "R1" for d in ds.districts)


def test_reps_per_district_in_range():
    from coach.synthetic import generate

    ds = generate(SEED)
    per_district = Counter(r.district_id for r in ds.reps)
    assert set(per_district) == {"D1", "D2"}
    for n in per_district.values():
        assert 8 <= n <= 12


def test_accounts_and_sessions_per_rep_in_range():
    from coach.synthetic import generate

    ds = generate(SEED)
    accts = Counter(a.rep_id for a in ds.accounts)
    for rep in ds.reps:
        assert 15 <= accts[rep.rep_id] <= 30

    sessions = Counter(s.rep_id for s in ds.coaching_sessions)
    for rep in ds.reps:
        assert sessions[rep.rep_id] in (0, 2, 3)


def test_edge_case_rep_with_no_history_exists():
    from coach.synthetic import generate

    ds = generate(SEED)
    reps_with_sessions = {s.rep_id for s in ds.coaching_sessions}
    reps_without = [r.rep_id for r in ds.reps if r.rep_id not in reps_with_sessions]
    assert reps_without, "expected at least one rep with no coaching history (edge case)"


# --------------------------------------------------------------- signal variety
def test_ranking_signals_vary_across_data():
    from coach.synthetic import generate

    ds = generate(SEED)
    # declining_share: share_trend spans negative and non-negative
    trends = [a.share_trend for a in ds.accounts]
    assert any(t < 0 for t in trends) and any(t >= 0 for t in trends)
    # low_call_activity: call counts vary (not all identical)
    calls = {c.calls for c in ds.call_activity}
    assert len(calls) > 1
    # missed_follow_up: both completed and missed follow-ups exist
    follow = {s.follow_up_done for s in ds.coaching_sessions}
    assert follow == {True, False}
    # opportunity_risk: more than one opportunity level present
    assert len({a.opportunity_level for a in ds.accounts}) > 1
    # sanity: the four signals are the expected fixed set
    assert SIGNALS == (
        "declining_share",
        "low_call_activity",
        "missed_follow_up",
        "opportunity_risk",
    )


# ------------------------------------------------------------------- PRP (T009)
def test_some_hcps_are_prp_and_at_least_one_exists():
    from coach.synthetic import generate

    ds = generate(SEED)
    prp_accounts = [a for a in ds.accounts if a.prp]
    assert prp_accounts, "expected at least one PRP-flagged HCP (data added in T009)"
    # PRP applies only to HCPs (prescriber data restriction), never plain accounts.
    assert all(a.type == AccountType.hcp for a in prp_accounts)
    # Realistic minority (well under half of all HCPs).
    hcps = [a for a in ds.accounts if a.type == AccountType.hcp]
    assert len(prp_accounts) < len(hcps) / 2


def test_prp_assignment_is_deterministic_for_seed():
    from coach.synthetic import generate

    a = {acct.account_id for acct in generate(SEED).accounts if acct.prp}
    b = {acct.account_id for acct in generate(SEED).accounts if acct.prp}
    assert a == b and a, "PRP set must be identical and non-empty for the same seed"


# ---------------------------------------------------------------- brands (T009)
def test_dataset_covers_all_five_brands():
    from coach.synthetic import generate

    ds = generate(SEED)
    brands_in_metrics = {m.brand for m in ds.account_brand_metrics}
    assert brands_in_metrics == set(Brand), "all five brands must appear in the metrics"
    # call activity is also per-brand and stays within the portfolio
    assert {c.brand for c in ds.call_activity} <= set(Brand)


def test_per_account_brand_metrics_exist_and_are_keyed():
    from coach.synthetic import generate

    ds = generate(SEED)
    assert ds.account_brand_metrics, "expected per-(account, brand) metric rows"
    # composite (account_id, brand) key is unique
    keys = [(m.account_id, m.brand) for m in ds.account_brand_metrics]
    assert len(keys) == len(set(keys))
    # at least one account carries metrics across multiple brands
    per_account = Counter(m.account_id for m in ds.account_brand_metrics)
    assert any(n > 1 for n in per_account.values())
    # every metrics row maps to a real account
    account_ids = {a.account_id for a in ds.accounts}
    assert all(m.account_id in account_ids for m in ds.account_brand_metrics)


def test_brand_metrics_are_deterministic_for_seed():
    from coach.synthetic import generate

    dump = lambda ds: [m.model_dump() for m in ds.account_brand_metrics]  # noqa: E731
    assert dump(generate(SEED)) == dump(generate(SEED))


# ----------------------------------------------------------------- synthetic only
def test_data_is_marked_synthetic():
    from coach.synthetic import generate

    ds = generate(SEED)
    assert ds.meta.synthetic is True
    assert ds.meta.source == "synthetic"


# ------------------------------------------------------------- store round-trip
def test_store_round_trip_counts_match(tmp_path):
    from coach.synthetic import generate

    ds = generate(SEED)
    db = tmp_path / "coach.db"
    with SqliteStore(str(db)) as store:
        store.write_dataset(ds)
        for table, n in ds.meta.counts.items():
            assert store.count(table) == n


def test_store_reads_through_interface_for_a_dm(tmp_path):
    from coach.synthetic import generate

    ds = generate(SEED)
    db = tmp_path / "coach.db"
    with SqliteStore(str(db)) as store:
        store.write_dataset(ds)
        ctx = AccessContext(
            user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
        )
        reps = store.get_reps(ctx)
        expected = [r.rep_id for r in ds.reps if r.district_id == "D1"]
        assert sorted(r.rep_id for r in reps) == sorted(expected)
        # a rep's accounts are readable through the interface
        accounts = store.get_accounts(ctx, reps[0].rep_id)
        assert 15 <= len(accounts) <= 30
