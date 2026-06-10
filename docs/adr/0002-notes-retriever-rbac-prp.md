# ADR 0002: The notes retriever enforces RBAC and PRP at query time

**Status:** Accepted

## Context

The coaching-notes vector retriever is a **second path to data** alongside the structured
store. It does semantic search over free-text coaching notes. Without controls it could
return notes outside the caller's territory (an RBAC leak), or notes tied to a **PRP**-flagged
prescriber (a privacy/FR-020 leak) — bypassing the single-door guarantees the structured
reads already enforce.

The data-access layer is supposed to be the **one door** where RBAC scope and PRP scrubbing
are applied. A retriever that skipped them would be a backdoor.

## Decision

The retriever enforces the **same RBAC scope and the same PRP scrubbing at query time**,
reusing the existing helpers — it is **not a separate trust boundary**:

- **RBAC** — every query takes the caller's `AccessContext`. The retriever calls the existing
  `rbac.require_rep_in_scope` / `rbac.scoped_rep_ids`, so a caller can only retrieve notes for
  reps inside their scope (`self` / `district` / `region` / `all`); an out-of-scope request
  raises `ScopeError`, exactly like the structured reads.
- **PRP** — each indexed note carries the account/HCP it concerns. At query time the retriever
  calls the existing `rbac.prp_account_ids` and **drops any note tied to a PRP-flagged
  account** before returning results, at every scope level (including `all`).
- A **single guarded entry point** (`NotesRetriever.search_notes`) applies both filters, so
  there is no path that returns un-scoped or PRP notes.

## Options considered

1. **Filter at query time — CHOSEN.**
   - Pro: one index; simple; **reuses the existing RBAC + PRP helpers** (no second copy of the
     rules to drift).
   - Con: the filter must be applied on every query — covered by the single entry point + tests.

2. **Separate per-scope indexes (physical isolation).**
   - Pro: physical separation per territory.
   - Con: many indexes to build and keep in sync; heavy; overkill for the MVP. **Rejected.**

3. **Trust the structured store only, no vector search.**
   - Pro: simplest.
   - Con: loses semantic retrieval over free-text notes, which is the whole point of the
     ride-along-prep section this seam supports. **Rejected.**

## Consequences

- **All retrieval goes through one guarded entry point.** RBAC + PRP tests cover the retriever
  the same way they cover the structured reads.
- The embeddings provider and vector store sit **behind interfaces**: the MVP uses a
  deterministic in-memory cosine store + a lazy Bedrock (Titan) embedder (model id from
  config); production swaps in **Amazon Bedrock Knowledge Bases / OpenSearch** behind the same
  interface — and **must re-apply the same query-time RBAC + PRP filter**.
- Each indexed note is tied to the account/HCP it concerns (synthetic, deterministic in the
  MVP; sourced from the system of record in production) so PRP scrubbing has something to act
  on. This is index metadata only — it does not change the persisted `CoachingSession` schema.
- This is a SEAM only. The ride-along-prep component (T029–T031) that consumes the retriever
  is a separate, later task.
