# ADR 0003: Fixed-graph orchestration; narrate before expose

**Status:** Accepted

## Context

The morning brief is made of five independent section components (rep ranking, coaching
focus, ride-along prep, accounts/business context, opener). Something has to **compose** them
into one `CoachingBrief` for a chosen rep.

Two risks to manage:

1. **The orchestration must stay deterministic** and must not become an autonomous/agentic
   loop. Each section already decides its facts in code; the orchestrator must not let an LLM
   "re-plan", reorder, or re-decide the ranking (Principles I & VI).
2. **Narration is per-section.** Each section fills its human-readable wording with the LLM
   only at the end (its `narrate_*` step); until then it holds a placeholder
   (`(reason summary pending narration)`, etc.). A brief must **never** expose an un-narrated
   placeholder to a user.

## Decision

- **Fixed LangGraph DAG, deterministic node order.** The orchestrator is a compiled graph with
  a fixed shape: `rank_reps → select_rep → {coaching_focus, ride_along_prep, accounts_context}
  → opener → assemble_brief`. The three middle sections are independent and run in parallel;
  the opener runs **after** coaching focus + accounts (it is built from them); assembly runs
  last. No node loops or re-plans.
- **AccessContext threads through every node.** Each node calls its existing section component
  with the caller's `AccessContext`, so RBAC scope + PRP scrubbing hold for every read; the
  orchestrator never widens scope.
- **Each node narrates its own section** (calls the section's `narrate_*` with the injected
  LLM), so narration stays per-section and the facts stay code-decided.
- **Narrate-before-expose guard.** `assemble_brief` builds the `CoachingBrief`, then runs a
  guard that scans every section's summary/text fields and **raises** if any pending
  placeholder remains. An un-narrated brief can never be returned.

## Options considered

1. **Fixed DAG + assembly guard — CHOSEN.**
   - Pro: deterministic, inspectable, parallel section nodes; the guard makes
     "narrate before expose" a hard invariant.
   - Con: the graph shape is fixed in code (changing the brief shape means editing the graph).

2. **Free agentic loop where the LLM orchestrates.**
   - Pro: flexible.
   - Con: non-deterministic; the LLM could re-decide/reorder the ranking and invent steps —
     **breaks Principles I & VI**. **Rejected.**

3. **Plain sequential function calls (no graph).**
   - Pro: simplest; also deterministic.
   - Con: no explicit, inspectable structure and no parallel section nodes. Viable, but a
     LangGraph DAG gives an explicit, reviewable shape and lets the three independent sections
     run in parallel — **chosen as the graph form** over ad-hoc calls.

## Consequences

- Every assembled brief is **fully narrated before exposure** (the guard enforces it); a test
  asserts the guard raises on a placeholder.
- The graph is **deterministic and inspectable**: same seed + same (deterministic) LLM → the
  same brief, every time (the consistency check, SC-004).
- The brief is **pure data** — no action/mutation path (suggestion-only, FR-011).
- **Production keeps the same graph**, swapping the fake LLM/embeddings for Amazon Bedrock
  (model id from config) — the orchestration shape does not change.
- This is the assembly + rubric step. The **FastAPI endpoints, UI, and the deferred F6/F8
  route guards are a separate step** (5b) and are not built here.
