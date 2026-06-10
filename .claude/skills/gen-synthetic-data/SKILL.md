---
name: gen-synthetic-data
description: Generate the seeded synthetic dataset for the MVP — 1 region, 2 districts, 8-12 reps each, 15-30 accounts/HCPs per rep, 2-3 prior coaching sessions, plus per-(account, brand) metrics across the five brands (share, volume, spend, call activity), opportunity/risk flags, and a PRP flag on ~5-10% of HCPs. Repeatable via a fixed seed. Manual only.
disable-model-invocation: true
---

# Generate synthetic data

Build (or run, if it already exists) the seeded synthetic data generator so the
data is realistic, varied, and repeatable.

Shape to produce:
- 1 region containing 2 districts (needed to test RBAC: DM vs region-level role).
- Each district: 1 district manager and 8-12 reps.
- Each rep: 15-30 accounts/HCPs and 2-3 prior coaching sessions, plus call
  activity, market share, volume, spend, and opportunity/risk flags.
- PRP flag: mark a realistic minority of HCPs as `prp` (about 5-10%, with at least one
  always present) so the data-access PRP-scrubbing path has data to exercise.
- Per-(account, brand) metrics: each account carries metrics across some of the five
  brands (LUPRON PEDS, LUPRON URO, LUPRON GYN, Synthroid, LILETTA — from the `Brand`
  enum). Spread share, volume, spend, and call activity per brand; call activity carries a
  `brand`. Not every account needs every brand, but the dataset must cover all five.

Requirements:
- Use a FIXED random seed so every run produces the same data (tests depend on this).
  PRP assignment and the per-brand metrics must be deterministic for the seed.
- Write the data through the data-access layer's expected schema, into the local
  MVP stores (SQLite/DuckDB for structured data; the notes store for coaching notes).
- Make sure the four ranking signals VARY across reps, so the priority list is
  meaningful and includes a few clear edge cases.
- Draw brand names ONLY from the `Brand` enum (single source of truth) — no hard-coded
  brand strings.
- All data is synthetic. Never use or copy any real values.

After generating, print a short summary: counts per table and the seed used.
