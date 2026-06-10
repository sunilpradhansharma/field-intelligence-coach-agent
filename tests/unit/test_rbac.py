"""T017 — RBAC scope-level tests (enforced at the data-access layer, Principle V/FR-013).

Each scope level must see exactly its territory, and an out-of-scope read must raise
`ScopeError`. Role → scope-level comes from the single config source (no hard-coded role
names here — we resolve via `scope_level_for`). Uses the 2-district seed.
"""

import pytest

from coach.config.settings import scope_level_for
from coach.data_access.interface import AccessContext, ScopeError
from coach.data_access.sqlite_store import SqliteStore
from coach.schemas import Role, ScopeLevel
from coach.synthetic import generate

SEED = 42


@pytest.fixture
def store():
    ds = generate(SEED)
    s = SqliteStore(":memory:")
    s.write_dataset(ds)
    yield s, ds
    s.close()


def _ids(reps):
    return {r.rep_id for r in reps}


def _district_reps(ds, district_id):
    return {r.rep_id for r in ds.reps if r.district_id == district_id}


# ----------------------------------------------------------- config mapping (single source)
def test_role_to_scope_level_mapping_from_config():
    assert scope_level_for(Role.rep) == ScopeLevel.self_
    assert scope_level_for(Role.district_manager) == ScopeLevel.district
    assert scope_level_for(Role.regional_director) == ScopeLevel.region
    assert scope_level_for(Role.regional_business_executive) == ScopeLevel.region
    assert scope_level_for(Role.head_of_sales) == ScopeLevel.all_


# --------------------------------------------------------------------- each scope level
def test_district_scope_sees_only_own_district(store):
    s, ds = store
    ctx = AccessContext(
        user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
    )
    seen = _ids(s.get_reps(ctx))
    assert seen == _district_reps(ds, "D1")
    assert seen.isdisjoint(_district_reps(ds, "D2"))


def test_region_scope_sees_all_districts_in_region(store):
    s, ds = store
    ctx = AccessContext(user_id="region_r1", role=Role.regional_director, region_id="R1")
    seen = _ids(s.get_reps(ctx))
    assert seen == _district_reps(ds, "D1") | _district_reps(ds, "D2")


def test_all_scope_sees_everything(store):
    s, ds = store
    ctx = AccessContext(user_id="hos_1", role=Role.head_of_sales, region_id="R1")
    seen = _ids(s.get_reps(ctx))
    assert seen == {r.rep_id for r in ds.reps}


def test_self_scope_sees_only_own_rep(store):
    s, ds = store
    me = next(r for r in ds.reps if r.district_id == "D1")
    ctx = AccessContext(
        user_id="rep_u", role=Role.rep, region_id="R1", district_id="D1", rep_id=me.rep_id
    )
    assert _ids(s.get_reps(ctx)) == {me.rep_id}


# ---------------------------------------------------------------------- out-of-scope denial
def test_dm_out_of_scope_read_raises_scope_error(store):
    s, ds = store
    ctx = AccessContext(
        user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
    )
    d2_rep = next(r.rep_id for r in ds.reps if r.district_id == "D2")
    with pytest.raises(ScopeError):
        s.get_rep(ctx, d2_rep)
    with pytest.raises(ScopeError):
        s.get_accounts(ctx, d2_rep)
    with pytest.raises(ScopeError):
        s.get_coaching_sessions(ctx, d2_rep)


def test_out_of_scope_and_missing_rep_are_indistinguishable(store):
    # FR-014: an out-of-scope caller must NOT be able to tell "rep exists in another
    # district" from "rep does not exist" — both raise the SAME error (ScopeError),
    # raised BEFORE existence is revealed.
    s, ds = store
    ctx = AccessContext(
        user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
    )
    real_out_of_scope = next(r.rep_id for r in ds.reps if r.district_id == "D2")
    nonexistent = "rep_does_not_exist_zzz"
    with pytest.raises(ScopeError):
        s.get_rep(ctx, real_out_of_scope)
    with pytest.raises(ScopeError):
        s.get_rep(ctx, nonexistent)


def test_self_scope_cannot_read_another_rep(store):
    s, ds = store
    me, other = (r.rep_id for r in ds.reps[:2])
    ctx = AccessContext(user_id="rep_u", role=Role.rep, region_id="R1", rep_id=me)
    assert s.get_rep(ctx, me).rep_id == me  # own record is fine
    with pytest.raises(ScopeError):
        s.get_rep(ctx, other)


def test_in_scope_reads_return_data(store):
    s, ds = store
    ctx = AccessContext(
        user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
    )
    rep = next(r.rep_id for r in ds.reps if r.district_id == "D1")
    assert s.get_rep(ctx, rep).rep_id == rep
    assert isinstance(s.get_accounts(ctx, rep), list)
