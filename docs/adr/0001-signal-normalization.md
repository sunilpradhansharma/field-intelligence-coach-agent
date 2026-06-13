# ADR 0001: Normalize ranking signals before weighting

**Status:** Accepted — implemented and in effect (Phase 3, the deterministic ranking; the same
normalized rollup now also folds in the Phase 8 Summit signal).

## Context

The rep ranking combines four business signals into one score per rep:

- `declining_share` — a **fraction** (e.g. a summed share drop of `0.13`),
- `low_call_activity` — a **count** (e.g. `3`),
- `missed_follow_up` — a **count**,
- `opportunity_risk` — a **count**.

These signals are on very different scales. With the raw values fed straight into the
weighted sum, the count-style signals (which can run into the teens) dominate the fractional
share signal no matter what weights are configured. In other words, the configured weights
did **not** actually control each signal's influence — the scale did.

That conflicts with the constitution: ranking must be **fair** (Principle VI) and
**explainable** (Principle II). If a stakeholder asks "why is this rep ranked first?", the
honest answer was "because it had big counts," not "because of the weights we set" — which is
neither fair nor defensible.

## Decision

**Normalize each signal to a 0..1 range before applying its weight.** The normalization basis
is config-visible — a per-signal cap/divisor in `Settings.ranking_norm_caps` where "a value at
or above the cap = 1.0":

```
normalized = min(raw, cap) / cap        # cap from config; saturates at 1.0
score      = sum(normalized * weight)   # weights from config
```

After normalization every signal sits on the same 0..1 scale, so the **weights are the only
thing controlling relative influence**. The structured reason still shows the underlying raw
data, so the DM (and any reviewer) still sees real numbers — see Consequences.

## Options considered

1. **Normalize to 0..1, then weight — CHOSEN.**
   - Pro: the weights become meaningful and defensible; influence is fair across signals;
     the result is explainable.
   - Con: requires choosing a normalization cap per count signal, which is a product
     judgment; caps need tuning with the business.

2. **Keep raw values, document the scale only.**
   - Pro: least work; fully deterministic.
   - Con: the weights stay misleading; counts dominate; hard to defend "why ranked first" to
     stakeholders. **Rejected.**

3. **Z-score / statistical normalization across reps.**
   - Pro: adapts to the data automatically.
   - Con: introduces cross-rep coupling — a rep's score would depend on the other reps in the
     set, which breaks per-rep determinism and makes the score harder to explain.
     **Rejected for the MVP.**

## Consequences

- Scores **changed** versus the pre-normalization version (they are now in `0..1`); the T021
  golden fixture was regenerated. Normalization also reordered the two top District-1 reps.
- The normalization caps are **config-visible and tunable** (`Settings.ranking_norm_caps`,
  env-overridable). Sensible defaults are set now: `declining_share = 3.0`,
  `low_call_activity = 10`, `missed_follow_up = 3`, `opportunity_risk = 10`. They should be
  reviewed with the business once real output is seen.
- The reason object now **distinguishes the raw value from the normalized value**:
  `SignalContribution` carries both `raw_value` (the real aggregate) and `normalized_value`
  (the 0..1 value used in scoring), plus `weight` and `contribution = normalized_value *
  weight`. Top-contributor data points still show real per-(account, brand) figures.
- The ranking remains **deterministic and pure** — each rep is scored independently from its
  own data (no cross-rep coupling), and the LLM still never decides ranks or scores.

## Open follow-up

- Confirm/tune the normalization caps with the business once they see real output.
