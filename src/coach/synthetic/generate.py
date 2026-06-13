"""Seeded synthetic data generator (Principle III: synthetic only).

Produces, from a FIXED seed (repeatable):
- 1 region, 2 districts (so RBAC can be tested later: DM vs RBD region view);
- each district: 1 district manager + 8-12 reps (and one shared RBD for the region);
- each rep: 15-30 accounts/HCPs, 2-3 prior coaching sessions (a few reps get 0 — an
  edge case), plus call activity, market share, volume, spend, and opportunity/risk.
- per-(account, brand) metrics + call activity across the five-brand portfolio (each
  account carries 1-3 brands); a 5-10% minority of HCPs are flagged PRP (the data is
  ADDED here — scrubbing prp=True HCPs is a later task, T008A).

The four ranking signals are made to VARY across reps via per-rep "need profiles", with
a few deliberately clear edge cases (a high-need rep, a low-need rep, a rep with no
coaching history, and a rep with sparse call activity).

All values are fabricated. No real customer, prescriber, or rep data is used.
"""

from __future__ import annotations

import argparse
import random

from coach.config import get_settings
from coach.schemas import (
    Account,
    AccountBrandMetrics,
    AccountType,
    Brand,
    CallActivity,
    CoachingSession,
    Dataset,
    District,
    GenerationMeta,
    OpportunityLevel,
    Performance,
    Region,
    Rep,
    Role,
    User,
)

_PERIOD = "2026-05"

# Per-profile generation parameters. Keep deterministic given the rng.
_PROFILES = ("high", "med", "low")

# Roughly 5-10% of HCPs are PRP-restricted (data ADDED here; scrubbing is T008A).
_PRP_RATE = 0.08


def _profile_metrics(
    rng: random.Random, profile: str
) -> tuple[float, OpportunityLevel, Performance, bool]:
    """Profile-driven (share_trend, opportunity, performance, risk) — shared by the
    account-level summary and the per-(account, brand) metrics so signal direction is
    consistent. Deterministic given `rng`."""
    if profile == "high":
        share_trend = round(rng.uniform(-0.15, -0.03), 4)
        opp = rng.choices(
            [OpportunityLevel.high, OpportunityLevel.med, OpportunityLevel.low],
            weights=[5, 3, 2],
        )[0]
        perf = rng.choice([Performance.under, Performance.on])
        risk = rng.random() < 0.4
    elif profile == "low":
        share_trend = round(rng.uniform(0.0, 0.12), 4)
        opp = rng.choices(
            [OpportunityLevel.low, OpportunityLevel.med, OpportunityLevel.high],
            weights=[5, 3, 2],
        )[0]
        perf = rng.choice([Performance.on, Performance.over])
        risk = rng.random() < 0.1
    else:  # med
        share_trend = round(rng.uniform(-0.06, 0.06), 4)
        opp = rng.choice(list(OpportunityLevel))
        perf = rng.choice(list(Performance))
        risk = rng.random() < 0.25
    return share_trend, opp, perf, risk


def _brands_for(rng: random.Random) -> list[Brand]:
    """1-3 distinct brands an account carries (not every account carries every brand).
    Drawn from the `Brand` enum only — no hard-coded brand strings."""
    return rng.sample(list(Brand), rng.randint(1, 3))


def _district_rep_count(rng: random.Random) -> int:
    return rng.randint(8, 12)


def _profile_for(rng: random.Random, district_idx: int, rep_idx: int, last_idx: int) -> str:
    """Assign a need profile, forcing clear edge cases in the first district."""
    if district_idx == 0:
        if rep_idx == 0:
            return "high"  # clear high-need rep
        if rep_idx == 1:
            return "low"  # clear low-need rep
    # All other reps get a varied, seeded profile.
    return rng.choice(_PROFILES)


def _account_for(rng: random.Random, rep: Rep, acct_n: int, profile: str) -> Account:
    share_trend, opp, perf, risk = _profile_metrics(rng, profile)
    acct_type = rng.choices([AccountType.hcp, AccountType.account], weights=[7, 3])[0]
    # PRP applies only to HCPs (prescriber data restriction). ~5-10% are flagged.
    prp = acct_type == AccountType.hcp and rng.random() < _PRP_RATE
    return Account(
        account_id=f"acct_{rep.rep_id}_{acct_n:02d}",
        rep_id=rep.rep_id,
        name=f"{'Dr.' if acct_type == AccountType.hcp else 'Acct'} {rep.rep_id[-3:]}-{acct_n:02d}",
        type=acct_type,
        market_share=round(rng.uniform(0.05, 0.45), 4),
        share_trend=share_trend,
        volume=round(rng.uniform(200, 5000), 1),
        spend=round(rng.uniform(500, 8000), 1),
        performance=perf,
        opportunity_level=opp,
        risk_flag=risk,
        prp=prp,
    )


def _brand_metrics_for(
    rng: random.Random, account: Account, profile: str, brand: Brand
) -> AccountBrandMetrics:
    """Per-(account, brand) metrics, profile-consistent (data-model.md I1)."""
    share_trend, opp, perf, risk = _profile_metrics(rng, profile)
    return AccountBrandMetrics(
        account_id=account.account_id,
        brand=brand,
        market_share=round(rng.uniform(0.05, 0.45), 4),
        share_trend=share_trend,
        volume=round(rng.uniform(200, 5000), 1),
        spend=round(rng.uniform(500, 8000), 1),
        performance=perf,
        opportunity_level=opp,
        risk_flag=risk,
    )


def _calls_for(
    rng: random.Random,
    account: Account,
    profile: str,
    sparse: bool,
    brand: Brand,
    opp: OpportunityLevel,
) -> CallActivity:
    if sparse:
        calls = rng.randint(0, 1)
        calls_trend = round(rng.uniform(-0.6, -0.2), 3)
    elif profile == "high":
        # high-need: low calls especially where opportunity is high (behavior mismatch)
        high_opp = opp == OpportunityLevel.high
        calls = rng.randint(0, 2) if high_opp else rng.randint(1, 4)
        calls_trend = round(rng.uniform(-0.5, 0.0), 3)
    elif profile == "low":
        calls = rng.randint(4, 9)
        calls_trend = round(rng.uniform(0.0, 0.4), 3)
    else:
        calls = rng.randint(2, 6)
        calls_trend = round(rng.uniform(-0.2, 0.2), 3)
    return CallActivity(
        activity_id=f"act_{account.account_id}_{brand.name}",
        rep_id=account.rep_id,
        account_id=account.account_id,
        brand=brand,
        period=_PERIOD,
        calls=calls,
        calls_trend=calls_trend,
    )


def _sessions_for(
    rng: random.Random, rep: Rep, profile: str, no_history: bool
) -> list[CoachingSession]:
    if no_history:
        return []  # edge case: brand-new rep, exercises empty-state later
    n = rng.choice([2, 3])
    sessions: list[CoachingSession] = []
    for k in range(n):
        # high-need reps are more likely to have a missed follow-up
        missed_prob = 0.6 if profile == "high" else 0.15
        follow_up_done = rng.random() > missed_prob
        sessions.append(
            CoachingSession(
                session_id=f"sess_{rep.rep_id}_{k + 1}",
                rep_id=rep.rep_id,
                date=f"2026-0{rng.randint(1, 5)}-{rng.randint(10, 28)}",
                notes_text=(
                    f"Synthetic coaching note {k + 1} for {rep.rep_id}: discussed account "
                    f"prioritization and approved assets."
                ),
                agreed_actions=[
                    "Build pre-call plans for top-5 accounts",
                    "Use the approved launch deck",
                ][: rng.randint(1, 2)],
                observe_next=["Opening value statement", "Objection handling"][: rng.randint(1, 2)],
                follow_up_done=follow_up_done,
            )
        )
    return sessions


def generate(seed: int) -> Dataset:
    """Build the full synthetic dataset deterministically from `seed`."""
    rng = random.Random(seed)

    region = Region(region_id="R1", name="Region 1")
    districts = [
        District(district_id="D1", region_id="R1", name="District 1"),
        District(district_id="D2", region_id="R1", name="District 2"),
    ]
    users = [
        User(
            user_id="dm_d1",
            name="DM District 1",
            role=Role.district_manager,
            region_id="R1",
            district_id="D1",
        ),
        User(
            user_id="dm_d2",
            name="DM District 2",
            role=Role.district_manager,
            region_id="R1",
            district_id="D2",
        ),
        # Region-scope user (RD) — full access across all districts in the region.
        User(
            user_id="region_r1",
            name="RD Region 1",
            role=Role.regional_director,
            region_id="R1",
            district_id=None,
        ),
        # All-scope user (Head of Sales) — full access across all regions.
        User(
            user_id="hos_1",
            name="Head of Sales",
            role=Role.head_of_sales,
            region_id="R1",
            district_id=None,
        ),
    ]

    reps: list[Rep] = []
    accounts: list[Account] = []
    account_brand_metrics: list[AccountBrandMetrics] = []
    call_activity: list[CallActivity] = []
    coaching_sessions: list[CoachingSession] = []

    for d_idx, district in enumerate(districts):
        rep_count = _district_rep_count(rng)
        last_idx = rep_count - 1
        # Edge-case reps in the first district:
        no_history_idx = last_idx if d_idx == 0 else -1
        sparse_calls_idx = 2 if (d_idx == 0 and rep_count > 2) else -1

        for r_idx in range(rep_count):
            rep = Rep(
                rep_id=f"rep_{district.district_id.lower()}_{r_idx + 1:03d}",
                name=f"Rep {district.district_id}-{r_idx + 1:02d}",
                district_id=district.district_id,
                tenure_months=rng.randint(3, 120),
            )
            reps.append(rep)
            profile = _profile_for(rng, d_idx, r_idx, last_idx)
            sparse = r_idx == sparse_calls_idx

            n_accounts = rng.randint(15, 30)
            for a_n in range(1, n_accounts + 1):
                account = _account_for(rng, rep, a_n, profile)
                accounts.append(account)
                # Per-(account, brand): one metrics row and one call-activity row per
                # brand the account carries (data-model.md I1). Call activity uses that
                # brand's opportunity so the behavior-vs-opportunity mismatch is aligned.
                for brand in _brands_for(rng):
                    metrics = _brand_metrics_for(rng, account, profile, brand)
                    account_brand_metrics.append(metrics)
                    call_activity.append(
                        _calls_for(rng, account, profile, sparse, brand, metrics.opportunity_level)
                    )

            coaching_sessions.extend(
                _sessions_for(rng, rep, profile, no_history=(r_idx == no_history_idx))
            )

    # Guarantee at least one PRP-flagged HCP exists for the fixed seed (deterministic:
    # flag the first HCP in id order if the sampling produced none).
    if not any(a.prp for a in accounts):
        for a in sorted(accounts, key=lambda x: x.account_id):
            if a.type == AccountType.hcp:
                a.prp = True
                break

    counts = {
        "regions": 1,
        "districts": len(districts),
        "users": len(users),
        "reps": len(reps),
        "accounts": len(accounts),
        "account_brand_metrics": len(account_brand_metrics),
        "call_activity": len(call_activity),
        "coaching_sessions": len(coaching_sessions),
    }
    return Dataset(
        meta=GenerationMeta(seed=seed, synthetic=True, source="synthetic", counts=counts),
        regions=[region],
        districts=districts,
        users=users,
        reps=reps,
        accounts=accounts,
        account_brand_metrics=account_brand_metrics,
        call_activity=call_activity,
        coaching_sessions=coaching_sessions,
    )


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Generate seeded synthetic data.")
    parser.add_argument("--seed", type=int, default=settings.seed)
    parser.add_argument("--db", type=str, default=settings.db_path)
    args = parser.parse_args()

    # Imported lazily so the generator module has no hard dependency on the store.
    from coach.data_access.sqlite_store import SCHEMA_VERSION, SqliteStore

    ds = generate(args.seed)
    with SqliteStore(args.db) as store:
        store.write_dataset(ds)  # stamps PRAGMA user_version = SCHEMA_VERSION

    print(
        f"Synthetic data generated (seed={args.seed}, synthetic={ds.meta.synthetic}, "
        f"schema=v{SCHEMA_VERSION}) -> {args.db}"
    )
    for table, n in ds.meta.counts.items():
        print(f"  {table:<18} {n}")


if __name__ == "__main__":
    main()
