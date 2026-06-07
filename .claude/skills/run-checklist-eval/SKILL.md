---
name: run-checklist-eval
description: Run the fixed-checklist evaluation on generated coaching briefs — confirm each brief has all 5 sections and every recommendation shows a visible reason. Reports pass/fail per section. Manual only.
disable-model-invocation: true
---

# Run the checklist evaluation

Check brief quality against the fixed rubric from the spec.

A brief PASSES only if all five sections are present AND each has a visible reason:
1. Which rep to ride with, and why (ranked, with reasons).
2. What to coach this rep on (1-3 focus areas, each with a reason).
3. What happened last time (prior notes, agreed actions, what to observe next).
4. Accounts/HCPs to focus on + business context, with mismatch flags.
5. A suggested opener for the morning conversation.

Steps:
1. Run the rubric tests (for example `pytest -q -k checklist or rubric`).
2. For each brief checked, report PASS/FAIL per section.
3. Confirm the example-based checks: for a known seeded input, the ranked list and
   reasons match the expected output.
4. Confirm no real data is present (synthetic-only).
5. Print a short summary table: section, pass/fail, note.
