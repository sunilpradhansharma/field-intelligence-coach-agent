# Contract: Orchestrator & the 5 Specialist Components

One LangGraph DAG wires five components into the brief. Each component is a pure callable
over the data-access interfaces and returns typed objects (see data-model.md), each
recommendation carrying a `Reason`. Components are shaped so each can later become its own
subagent without changing this contract.

## Orchestration graph (explicit DAG — no autonomous loops)

```text
            ┌─> coaching_focus ─┐
prioritize ─┼─> ride_along_prep ┼─> opener ─> assemble_brief
            └─> accounts_context┘
```
- `prioritize` runs first; the selected rep (default: rank 1, or DM-chosen) feeds the
  three section components, which run independently; `opener` consumes their outputs;
  `assemble_brief` aggregates + attaches audit metadata.
- Deterministic, acyclic, no self-directed tool selection (Principle I, VIII).

## 1. prioritization — `rank_reps(ctx, data) -> list[RepRanking]`
- **Deterministic** weighted-sum scorer over the four signals; fixed weights from config.
- Returns ranked reps + per-rep `Reason` (signals, weights, contributions, data points).
- LLM only narrates `reason.summary`; it MUST NOT change rank/score.
- **Guarantees**: identical seed → identical output; no protected attributes used; stable
  documented tie-break.

## 2. coaching_focus — `suggest_focus(ctx, rep_id, data) -> list[CoachingFocus]`
- Returns 1–3 focus areas, each with a data-tied `Reason`.
- If no notable gap exists, returns an explicit "no high-priority focus area" result
  rather than inventing one (FR-005 edge).

## 3. ride_along_prep — `prep(ctx, rep_id) -> RideAlongPrep | EmptyState`
- RAG over coaching notes (Retriever) + structured session fields.
- Returns last session notes, `agreed_actions`, `observe_next`.
- Returns `EmptyState` when the rep has no sessions (FR-018).

## 4. accounts_context — `key_accounts(ctx, rep_id, data) -> list[AccountFocus]`
- Returns a focused list (not the whole book) with business context
  (share, share_trend, volume, spend, performance, calls_trend).
- Flags behavior-vs-opportunity mismatch (e.g., low calls on high opportunity) with a
  `Reason` (FR-008). Reports missing data instead of fabricating.

## 5. opener — `draft_opener(ctx, assembled_context) -> Opener`
- LLM drafts a short opener referencing the rep's specific points; carries a `Reason`
  linking it to the brief. Presented as an editable suggestion, never a required script
  (FR-009, Principle I).

## assemble_brief — `assemble(...) -> CoachingBrief`
- Aggregates sections; sets `synthetic=true`, `brief_id`, `generated_for`.
- Emits one audit record (who/role/scope/rep/brief_id/timestamp) via observability.
- **Validation**: rejects assembly if any recommendation lacks a non-empty `reason`
  (FR-010) — surfaced as a test failure and a runtime guard.

## Invariants tested (maps to rubric / IX)
- Brief is "complete" only if all 5 sections present AND each has a visible reason.
- Every component output is RBAC-scoped (it only ever received in-scope data).
- Ranking/scoring reproducible against seeded golden fixtures.
