---
name: gen-synthetic-data
description: Generate the seeded synthetic dataset for the MVP — 1 region, 2 districts, 8-12 reps each, 15-30 accounts/HCPs per rep, 2-3 prior coaching sessions, plus call activity, share, volume, spend, and opportunity/risk flags. Repeatable via a fixed seed. Manual only.
disable-model-invocation: true
---

# Generate synthetic data

Build (or run, if it already exists) the seeded synthetic data generator so the
data is realistic, varied, and repeatable.

Shape to produce:
- 1 region containing 2 districts (needed to test RBAC: DM vs RBD region view).
- Each district: 1 district manager and 8-12 reps.
- Each rep: 15-30 accounts/HCPs and 2-3 prior coaching sessions, plus call
  activity, market share, volume, spend, and opportunity/risk flags.

Requirements:
- Use a FIXED random seed so every run produces the same data (tests depend on this).
- Write the data through the data-access layer's expected schema, into the local
  MVP stores (SQLite/DuckDB for structured data; the notes store for coaching notes).
- Make sure the four ranking signals VARY across reps, so the priority list is
  meaningful and includes a few clear edge cases.
- All data is synthetic. Never use or copy any real values.

After generating, print a short summary: counts per table and the seed used.
