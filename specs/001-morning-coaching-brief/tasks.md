---
description: "Task list for Morning Coaching Brief (MVP)"
---

# Tasks: Morning Coaching Brief (MVP)

**Input**: Design documents from `specs/001-morning-coaching-brief/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: REQUESTED by the user — each component is paired with a test task; RBAC,
deterministic ranking, example-based (seeded) checks, and the 5-section checklist rubric
are all encoded as automated pytest tasks.

**Organization**: Grouped by user story (US1–US5 from spec.md). The architecture rules
from the plan/constitution drive the ordering: the **data-access interface** and the
**seeded synthetic generator** and **RBAC** come first (Phase 2, foundational), before any
component; the **rep ranking is a deterministic, code-only function** (its own task,
separate from the LLM); the **LLM only narrates the structured reason**.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1–US5 (user story phases only)
- Exact file paths included in each task

## Path Conventions

Web-service layout from plan.md: source under `src/coach/`, UI under `web/`, tests under
`tests/{unit,component,e2e}/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and tooling.

- [ ] T001 Create project structure (`src/coach/{config,data_access,synthetic,llm,guardrails,components,orchestrator,observability,api}/`, `web/`, `tests/{unit,component,e2e}/`) per plan.md
- [ ] T002 Initialize Python 3.11 project with deps (FastAPI, LangGraph, boto3, duckdb/sqlite3, faiss-cpu/chromadb, pydantic, pytest) in `pyproject.toml`; configure `uv sync`
- [ ] T003 [P] Configure ruff lint+format and pytest in `pyproject.toml` / `ruff.toml` (matches the project format hook)
- [ ] T004 [P] Implement config module in `src/coach/config/settings.py` — reads `BEDROCK_MODEL_ID`, `AWS_REGION`, `BEDROCK_EMBED_MODEL_ID`, `COACH_DB_PATH`, `COACH_SEED`, and the fixed ranking weights from env/config (NEVER hard-code the model id)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST exist before ANY component. Implements the
plan's "interface first, generator early, RBAC in the data layer" rules.

**⚠️ CRITICAL**: No user story (component) work begins until this phase is complete.

### Interfaces, schemas, store, data, RBAC

- [ ] T005 Define the data-access interface + `AccessContext` in `src/coach/data_access/interface.py` (`DataAccess` and `Retriever` Protocols, `AccessContext`, `ScopeError`) per contracts/data-access.md — **all components depend on this; built FIRST**
- [ ] T006 [P] Implement Pydantic schemas (entities + `Reason`, `SignalContribution`, `RepRanking`, `CoachingFocus`, `AccountFocus`, `RideAlongPrep`/`EmptyState`, `Opener`, `CoachingBrief`) in `src/coach/schemas.py` per data-model.md
- [ ] T007 Implement the structured store behind the interface in `src/coach/data_access/sqlite_store.py` (SQLite/DuckDB; `synthetic=true`) — depends on T005
- [ ] T008 Implement **RBAC scoping inside the data-access layer** in `src/coach/data_access/rbac.py` and enforce it in every `sqlite_store` read (DM=own district; RBD=region, read-only; out-of-scope → `ScopeError`) — depends on T005, T007
- [ ] T009 Implement the **seeded synthetic data generator** in `src/coach/synthetic/generate.py` (1 region, 2 districts, 1 DM + 8–12 reps each, 15–30 accounts/HCPs/rep, 2–3 coaching sessions, call activity, share, volume, spend, opportunity/risk; **four ranking signals VARY across reps** incl. edge cases; some reps have 0 sessions) writing through the store schema; fixed seed; prints per-table counts + seed — depends on T007

### Provider seams (Bedrock, vector store, guardrail, observability)

- [ ] T010 [P] Implement Bedrock embeddings (Titan) `Embedder` in `src/coach/llm/embeddings.py` (model id from config) per contracts/data-access.md
- [ ] T011 Implement the FAISS/Chroma `Retriever` in `src/coach/data_access/faiss_retriever.py` and index coaching notes (RBAC-scoped retrieval) — depends on T005, T010, T009
- [ ] T012 [P] Implement the Bedrock Claude `LLM` wrapper in `src/coach/llm/client.py` (model id from config; only `narrate(reason)` / `draft_opener()` — MUST NOT compute or alter rankings)
- [ ] T013 [P] Implement the PII `Guardrail` seam in `src/coach/guardrails/pii.py` (pass-through hook for MVP → Bedrock Guardrails in prod)
- [ ] T014 [P] Implement audit/observability in `src/coach/observability/audit.py` (structured per-brief and per-LLM-call records; no out-of-scope data, no raw PII)

### Orchestrator + API skeleton

- [ ] T015 Implement LangGraph orchestrator skeleton (explicit DAG, no loops) + brief assembly stub in `src/coach/orchestrator/graph.py` and `src/coach/orchestrator/brief.py` (rejects any recommendation lacking a non-empty `reason`) — depends on T006
- [ ] T016 Implement FastAPI app skeleton + simulated identity → `AccessContext` (`X-User-Id`) + `GET /api/whoami` in `src/coach/api/app.py` — depends on T008

### Foundational tests (RBAC, data, schema)

- [ ] T017 [P] Unit tests for **RBAC** in `tests/unit/test_rbac.py` — DM sees only own district; RBD sees both districts read-only; out-of-scope read raises `ScopeError`; results contain zero out-of-scope rows (uses the 2-district seed)
- [ ] T018 [P] Unit tests for the data-access interface + generator in `tests/unit/test_data_access.py` — seeded counts match the required shape; same seed → identical data (repeatability); `synthetic=true`
- [ ] T019 [P] Unit tests for schemas in `tests/unit/test_schemas.py` — every recommendation object requires a non-empty `reason`; assembly guard rejects a missing reason

**Checkpoint**: Interface, seeded data, RBAC, provider seams, orchestrator/API skeletons ready and tested. Component work can begin.

---

## Phase 3: User Story 1 — See who to ride with and why (Priority: P1) 🎯 MVP

**Goal**: Brief section 1 — a ranked list of reps needing attention, each with a visible, data-backed reason.

**Independent Test**: `GET /api/reps` as a DM returns a ranked list scoped to the DM's district where every rep carries a reason (signals + weights + data points); RBD sees both districts.

### Tests for User Story 1 ⚠️ (write first, ensure they fail)

- [ ] T020 [P] [US1] Unit test the **deterministic scorer** in `tests/unit/test_prioritization.py` — fixed visible weights applied to the 4 signals, documented stable tie-break, identical seed → identical ranks/scores (no LLM in the path)
- [ ] T021 [P] [US1] Example-based test in `tests/component/test_prioritization_golden.py` — known seeded District 1 input → ranked rep ids, scores, and `reason` objects match the committed golden fixture exactly
- [ ] T022 [P] [US1] Component test in `tests/component/test_reps_endpoint.py` — `GET /api/reps` is RBAC-scoped, every rep has a non-empty reason, `limit` honored

### Implementation for User Story 1

- [ ] T023 [US1] Implement the **deterministic prioritization scoring function** in `src/coach/components/prioritization.py` — pure code, fixed visible weights from config over the 4 signals; returns `list[RepRanking]` + `Reason` (signals, weights, contributions, data points). **The LLM does NOT decide ranking.** Depends on T005, T006, T009
- [ ] T024 [US1] Implement LLM **reason narration** (separate task) in `src/coach/components/narrate.py` — turns the structured `Reason` into clear language via the LLM wrapper, without changing any rank/score. Depends on T012, T023
- [ ] T025 [US1] Wire the `prioritize` node into the graph and implement `GET /api/reps` in `src/coach/api/app.py` (audit record emitted). Depends on T015, T016, T023, T024

**Checkpoint**: US1 fully functional and independently testable — this is the MVP slice.

---

## Phase 4: User Story 2 — What to coach this rep on (Priority: P2)

**Goal**: Brief section 2 — 1–3 coaching focus areas for the selected rep, each with a reason.

**Independent Test**: For a seeded rep, the brief returns 1–3 focus areas each with a data-tied reason; a rep with no notable gap returns an explicit "no high-priority focus area".

### Tests for User Story 2 ⚠️

- [ ] T026 [P] [US2] Component + example-based test in `tests/component/test_coaching_focus.py` — 1–3 focus areas, each with a reason; seeded input → expected focus areas; no-gap edge case handled

### Implementation for User Story 2

- [ ] T027 [US2] Implement `coaching_focus` component in `src/coach/components/coaching_focus.py` — deterministic selection of 1–3 focus areas + data-tied `Reason`; LLM only phrases the reason text. Depends on T005, T006, T023
- [ ] T028 [US2] Wire the `coaching_focus` node into the graph and into the brief (section 2) in `src/coach/orchestrator/graph.py`. Depends on T015, T027

**Checkpoint**: US1 + US2 both independently functional.

---

## Phase 5: User Story 3 — Ride-along prep (Priority: P2)

**Goal**: Brief section 3 — prior notes, agreed actions, and what to observe next (RAG over coaching notes).

**Independent Test**: For a rep with history, returns last notes + agreed actions + observe-next; for a rep with none, returns an explicit empty state.

### Tests for User Story 3 ⚠️

- [ ] T029 [P] [US3] Component test in `tests/component/test_ride_along_prep.py` — retrieval is RBAC-scoped; empty-state for a no-history rep; seeded input → expected retrieved items

### Implementation for User Story 3

- [ ] T030 [US3] Implement `ride_along_prep` component in `src/coach/components/ride_along_prep.py` — RAG via `Retriever` + structured `agreed_actions`/`observe_next`; returns `EmptyState` when no sessions. Depends on T011, T006
- [ ] T031 [US3] Wire the `ride_along_prep` node into the graph and into the brief (section 3). Depends on T015, T030

**Checkpoint**: US1–US3 independently functional.

---

## Phase 6: User Story 4 — Accounts/HCPs & business context (Priority: P2)

**Goal**: Brief section 4 — key accounts/HCPs with business context and behavior-vs-opportunity mismatch flags.

**Independent Test**: For a seeded rep, returns a focused account list with context (share, volume, performance, spend, calls trend) and at least one mismatch flag where warranted; all in-scope.

### Tests for User Story 4 ⚠️

- [ ] T032 [P] [US4] Component + example-based test in `tests/component/test_accounts_context.py` — focused list (not whole book), context fields present, mismatch flagging (low calls on high opportunity), RBAC-scoped, missing-data reported not fabricated

### Implementation for User Story 4

- [ ] T033 [US4] Implement `accounts_context` component in `src/coach/components/accounts_context.py` — selects key accounts, attaches business context, flags mismatches, each with a `Reason`. Depends on T005, T006, T009
- [ ] T034 [US4] Wire the `accounts_context` node into the graph and into the brief (section 4). Depends on T015, T033

**Checkpoint**: US1–US4 independently functional.

---

## Phase 7: User Story 5 — Suggested opener (Priority: P3)

**Goal**: Brief section 5 — a short suggested opener referencing the rep's specifics; the full `/api/brief/{rep_id}` now returns all five sections.

**Independent Test**: For a populated brief, returns a short opener referencing this rep's points, carrying a reason, presented as an editable suggestion.

### Tests for User Story 5 ⚠️

- [ ] T035 [P] [US5] Component test in `tests/component/test_opener.py` — opener references rep-specific points, carries a reason, is presented as suggestion-only (no action)

### Implementation for User Story 5

- [ ] T036 [US5] Implement `opener` component in `src/coach/components/opener.py` — LLM drafts a short opener from the assembled context + a `Reason`; suggestion only. Depends on T012, T006
- [ ] T037 [US5] Wire the `opener` node into the graph and implement `GET /api/brief/{rep_id}` (full 5-section brief, RBAC `403` on out-of-scope, audit record) in `src/coach/api/app.py`. Depends on T015, T016, T036, and T028/T031/T034

**Checkpoint**: All five sections of the brief are generated.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Whole-brief quality, UI, audit, and validation.

- [ ] T038 Implement the **5-section checklist rubric** e2e test in `tests/e2e/test_brief_rubric.py` — a brief PASSES only if all 5 sections are present AND every recommendation has a visible reason (encodes the fixed rubric; SC-002/004/005/006)
- [ ] T039 [P] Implement the minimal web page in `web/index.html` — renders the 5 sections and each `reason` block (suggestions only; DM decides)
- [ ] T040 [P] Audit assertions in `tests/e2e/test_audit.py` — one record per brief generation and per LLM call; no out-of-scope data, no raw PII
- [ ] T041 [P] Synthetic-only guard test in `tests/e2e/test_synthetic_only.py` — every data response carries `synthetic=true`; no real connector is configured (SC-007)
- [ ] T042 End-to-end run of quickstart.md scenarios A–D in `tests/e2e/test_quickstart.py` (happy path, RBAC, empty/sparse, determinism golden)
- [ ] T043 [P] Update `README.md` / docs with run + eval instructions (`/gen-synthetic-data`, `/run-checklist-eval`)

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup. **BLOCKS all user stories.** Within it the order is: interface (T005) → schemas (T006) → store (T007) → RBAC (T008) → generator (T009) → retriever/embedder (T010, T011) → seams (T012–T014) → skeletons (T015, T016) → foundational tests (T017–T019).
- **User Stories (Phase 3–7)**: all depend on Foundational. US1 is the MVP. US2/US3/US4 are independent of each other; US5's full-brief endpoint (T037) depends on US2/US3/US4 nodes being wired.
- **Polish (Phase 8)**: depends on the stories whose output it validates (rubric/quickstart need all five sections).

### Critical-path (constitution/architecture) rules honored

- T005 (interface) precedes every component — components never read a store directly.
- T009 (seeded generator) precedes data-consuming components and example-based tests.
- T008 (RBAC) lives in the data-access layer with its own tests (T017).
- T023 (deterministic ranking) is code-only and separate from T024 (LLM narration).

### Parallel opportunities

- Setup: T003, T004 in parallel.
- Foundational: T006 ∥ (T010, T012, T013, T014) once T005 exists; foundational tests T017 ∥ T018 ∥ T019 after their targets.
- US1 tests T020 ∥ T021 ∥ T022 (write first).
- Across stories after Foundational: US2, US3, US4 components can be built in parallel by different developers; their test tasks (T026, T029, T032) are [P].
- Polish: T039 ∥ T040 ∥ T041 ∥ T043.

---

## Parallel Example: User Story 1

```bash
# Write US1 tests together first (they should fail):
Task: "Unit test deterministic scorer in tests/unit/test_prioritization.py"           # T020
Task: "Example-based golden test in tests/component/test_prioritization_golden.py"      # T021
Task: "Component test GET /api/reps in tests/component/test_reps_endpoint.py"           # T022
```

---

## Implementation Strategy

### MVP first (User Story 1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational (interface, seeded data, RBAC, seams, skeletons) → 3. Phase 3 US1 (deterministic ranking + reason narration + `/api/reps`) → **STOP and validate** US1 independently (ranked reps, every reason visible, RBAC enforced).

### Incremental delivery

Foundation → US1 (MVP) → US2 → US3 → US4 → US5 (full brief) → Polish (rubric, UI, audit, quickstart). Each story is an independently testable increment.

---

## Notes

- [P] = different files, no dependency on an incomplete task.
- The ranking (T023) is deterministic and testable; the LLM (T024, T027 phrasing, T036) only renders/drafts language and never decides priority — Principles I & VI.
- Every recommendation carries a structured `reason`; the assembly guard (T015) and rubric test (T038) enforce it — Principle II.
- All reads are RBAC-scoped at the data layer (T008) — Principle V.
- Synthetic only; `synthetic=true` enforced (T041) — Principle III.
- Verify tests fail before implementing; commit after each task or logical group.
