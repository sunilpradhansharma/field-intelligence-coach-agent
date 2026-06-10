"""T017A — PRP scrubbing tests (FR-020, enforced at the data-access layer).

PRP-flagged HCPs (and their dependent call-activity rows) must never be returned through
any data-access read, at every scope level. Deterministic for the fixed seed, and the seed
must contain at least one PRP HCP so the test is meaningful.
"""

import pytest

from coach.data_access.interface import AccessContext
from coach.data_access.sqlite_store import SqliteStore
from coach.schemas import Role
from coach.synthetic import generate

SEED = 42


def _prp_account_ids(ds):
    return {a.account_id for a in ds.accounts if a.prp}


def test_seed_contains_at_least_one_prp_hcp_deterministically():
    a = _prp_account_ids(generate(SEED))
    b = _prp_account_ids(generate(SEED))
    assert a, "seed must contain at least one PRP HCP for this test to be meaningful"
    assert a == b, "PRP set must be identical for the same seed"


@pytest.fixture
def store():
    ds = generate(SEED)
    s = SqliteStore(":memory:")
    s.write_dataset(ds)
    yield s, ds
    s.close()


def _all_scope_contexts():
    """One AccessContext per non-self scope level (all read paths must scrub PRP)."""
    return [
        AccessContext(
            user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
        ),
        AccessContext(user_id="region_r1", role=Role.regional_director, region_id="R1"),
        AccessContext(user_id="hos_1", role=Role.head_of_sales, region_id="R1"),
    ]


def test_no_prp_account_returned_at_any_scope_level(store):
    s, ds = store
    prp_ids = _prp_account_ids(ds)
    assert prp_ids  # guard

    for ctx in _all_scope_contexts():
        for rep in s.get_reps(ctx):
            accounts = s.get_accounts(ctx, rep.rep_id)
            assert all(not a.prp for a in accounts)
            assert prp_ids.isdisjoint({a.account_id for a in accounts})
            # business metrics derive from accounts → also scrubbed
            metrics = s.get_business_metrics(ctx, rep.rep_id)
            assert prp_ids.isdisjoint({m.account_id for m in metrics})
            # call activity tied to a PRP account must be scrubbed too
            calls = s.get_call_activity(ctx, rep.rep_id)
            assert prp_ids.isdisjoint({c.account_id for c in calls})


def test_self_scope_also_scrubs_prp(store):
    s, ds = store
    prp_ids = _prp_account_ids(ds)
    rep = ds.reps[0]
    ctx = AccessContext(user_id="rep_u", role=Role.rep, region_id="R1", rep_id=rep.rep_id)
    accounts = s.get_accounts(ctx, rep.rep_id)
    assert prp_ids.isdisjoint({a.account_id for a in accounts})
    calls = s.get_call_activity(ctx, rep.rep_id)
    assert prp_ids.isdisjoint({c.account_id for c in calls})


def test_prp_scrubbing_is_deterministic_for_seed(store):
    s, ds = store
    ctx = AccessContext(user_id="hos_1", role=Role.head_of_sales, region_id="R1")
    rep = ds.reps[0].rep_id

    def snapshot():
        return [a.account_id for a in s.get_accounts(ctx, rep)]

    assert snapshot() == snapshot()
