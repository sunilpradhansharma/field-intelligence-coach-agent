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

- [X] T001 Create project structure (`src/coach/{config,data_access,synthetic,llm,guardrails,components,orchestrator,observability,api}/`, `web/`, `tests/{unit,component,e2e}/`) per plan.md
- [X] T002 Initialize Python 3.11 project with deps (FastAPI, LangGraph, boto3, duckdb/sqlite3, faiss-cpu/chromadb, pydantic, pytest) in `pyproject.toml`; configure `uv sync`
- [X] T003 [P] Configure ruff lint+format and pytest in `pyproject.toml` / `ruff.toml` (matches the project format hook)
- [X] T004 [P] Implement config module in `src/coach/config/settings.py` — reads `BEDROCK_MODEL_ID`, `AWS_REGION`, `BEDROCK_EMBED_MODEL_ID`, `COACH_DB_PATH`, `COACH_SEED`, and the fixed ranking weights from env/config (NEVER hard-code the model id)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST exist before ANY component. Implements the
plan's "interface first, generator early, RBAC in the data layer" rules.

**⚠️ CRITICAL**: No user story (component) work begins until this phase is complete.

### Interfaces, schemas, store, data, RBAC

- [X] T005 Define the data-access interface + `AccessContext` in `src/coach/data_access/interface.py` (`DataAccess` and `Retriever` Protocols, `AccessContext`, `ScopeError`) per contracts/data-access.md — **all components depend on this; built FIRST**
- [X] T006 [P] Implement Pydantic schemas (entities + `Reason`, `SignalContribution`, `RepRanking`, `CoachingFocus`, `AccountFocus`, `RideAlongPrep`/`EmptyState`, `Opener`, `CoachingBrief`) in `src/coach/schemas.py` per data-model.md
- [X] T007 Implement the structured store behind the interface in `src/coach/data_access/sqlite_store.py` (SQLite/DuckDB; `synthetic=true`) — depends on T005
- [ ] T007A **(Planned — Phase 1/2 amendment)** Add `prp` and brand columns + Brand enum: add the `prp` boolean to the HCP/account schema in `src/coach/data_access/sqlite_store.py`, add per-(account, brand) brand attribution to the performance and call-activity fields (see data-model.md I1 decision), and create the `Brand` enum (single source of truth) in `src/coach/config`/`src/coach/schemas.py`. **MUST run BEFORE T008A (PRP enforcement) and before the T009 generator amendment**, because both read these columns/enum. Links: FR-020 and the brand-portfolio assumption. Depends on T005, T007
- [X] T008 Implement **RBAC scoping inside the data-access layer** in `src/coach/data_access/rbac.py` and enforce it in every `sqlite_store` read by **territory scope level**: `self` (rep), `district` (DM — own district only), `region` (region-level roles — all districts in their region), `all` (top sales role — all regions). All non-rep levels have **full access** (not read-only); the role-name → scope-level mapping comes from a single config/enum source. Out-of-scope read → `ScopeError`. — depends on T005, T007
- [X] T008A Implement **PRP scrubbing at the data-access layer** — every `sqlite_store` read (and the retriever) MUST drop HCPs flagged `prp = true` before returning results, so no PRP HCP reaches a field user (FR-020, refines FR-016). Lives alongside RBAC in the data-access layer. Depends on T005, T007, **T007A** (the `prp` column must exist), T008
- [X] T009 Implement the **seeded synthetic data generator** in `src/coach/synthetic/generate.py` (1 region, 2 districts, 1 DM + 8–12 reps each, 15–30 accounts/HCPs/rep, 2–3 coaching sessions, call activity, share, volume, spend, opportunity/risk; **four ranking signals VARY across reps** incl. edge cases; some reps have 0 sessions) writing through the store schema; fixed seed; prints per-table counts + seed — depends on T007
  - **(Phase 1 amendment — PRP)**: the generator MUST produce some HCPs flagged `prp = true` so the PRP scrubbing path (T008A) and its test (T017A) have data to exercise. Runs AFTER T007A (the `prp` column must exist).
  - **(Phase 1 amendment — brands)**: the generator MUST spread performance data (share, volume, spend, call activity) across the five-brand portfolio — LUPRON PEDS, LUPRON URO, LUPRON GYN, Synthroid, LILETTA — as per-(account, brand) metrics (see data-model.md I1 decision), drawing brand names from the single `Brand` enum/config source (T007A), not hard-coded literals. Runs AFTER T007A.
  - **(Amendment impact — tests)**: because this amendment changes the generated data/counts, the existing seeded **count/shape test T018 MUST be updated and re-run** to match the amended (PRP + 5-brand) seed, and the **T021 golden fixture MUST be authored against the amended seed** (not the pre-amendment data).

### Provider seams (Bedrock, vector store, guardrail, observability)

- [X] T010 [P] Implement Bedrock embeddings (Titan) `EmbeddingProvider` in `src/coach/llm/embeddings.py` (model id from config; lazy boto3; deterministic `FakeEmbeddings` for offline tests) per contracts/data-access.md
- [X] T011 Implement the `Retriever` seam in `src/coach/data_access/notes_retriever.py` (+ `vector_store.py`: a `VectorStore` interface with an in-memory cosine store for the MVP → Chroma / Bedrock Knowledge Bases / OpenSearch in prod). Indexes coaching notes and enforces the **same RBAC scope + PRP scrubbing at query time** (reuses `rbac.require_rep_in_scope` / `scoped_rep_ids` / `prp_account_ids`); single guarded entry point `search_notes`. See **docs/adr/0002-notes-retriever-rbac-prp.md**. NOTE: this is the seam only — the ride-along-prep component (T029–T031) that consumes it is separate. Depends on T005, T008/T008A, T010, T009
- [ ] T012 [P] Implement the Bedrock Claude `LLM` wrapper in `src/coach/llm/client.py` (model id from config; only `narrate(reason)` / `draft_opener()` — MUST NOT compute or alter rankings)
- [ ] T013 [P] Implement the PII `Guardrail` seam in `src/coach/guardrails/pii.py` (pass-through hook for MVP → Bedrock Guardrails in prod)
- [X] T014 [P] Implement audit/observability in `src/coach/observability/audit.py` (structured per-brief and per-LLM-call records; no out-of-scope data, no raw PII). **Record field-level data classification** (rep fields = HR-sensitive; HCP fields = private/IQVIA-PDRP) so the logger knows which fields must never be emitted (FR-016) — `build_audit_record` enforces an allow-list of safe identifiers/metadata and REFUSES any HR-sensitive/private field by construction

### Orchestrator + API skeleton

- [X] T015 Implement the LangGraph orchestrator (**fixed DAG, no loops**) + brief assembly in `src/coach/orchestrator/brief_graph.py` and `src/coach/orchestrator/assembly.py`. Node order: rank → select_rep → {coaching_focus, ride_along_prep, accounts_context} (parallel) → opener (after focus + accounts) → assemble; the `AccessContext` threads through every node (RBAC + PRP hold; scope never widened). Each node runs the section's deterministic build AND its `narrate_*`. Assembly builds `CoachingBrief` and runs the **narrate-before-expose guard** (`assert_narrated` RAISES on any `PENDING_*` placeholder). New schemas `CoachingBrief` + `GeneratedFor`; config `ranked_reps_max`. See **docs/adr/0003-orchestration-and-narrate-before-expose.md**. (Store now opens with `check_same_thread=False` so the parallel section reads work.) — depends on T006, T023–T036
- [X] T016 Implement FastAPI app skeleton + simulated identity → `AccessContext` (`X-User-Id`) + `GET /api/whoami` in `src/coach/api/app.py` — depends on T008. Read-only surface (GET only); identity resolves via the data-access layer (`SqliteStore.get_user`) → role → scope level from config (caller cannot choose scope); a fresh store connection is opened/closed PER REQUEST (a small per-thread pool in `SqliteStore`, maps to a connection pool / Aurora); clean error mapping (401 unknown identity, 403 out-of-scope/not-found indistinguishable, 500 without stack traces); LLM/embeddings injected via `AppDeps` (Bedrock lazy; tests use fakes)

### Foundational tests (RBAC, data, schema)

- [X] T017 [P] Unit tests for **RBAC scope levels** in `tests/unit/test_rbac.py` — assert each scope level sees exactly its territory: `district` (DM) sees only its own district; `region` (region-level roles, e.g. RD/RBE) sees all districts in its region (full access, not read-only); `all` (top sales role) sees all regions; and `self` (rep) sees only itself. Out-of-scope read raises `ScopeError`; results contain zero out-of-scope rows (uses the 2-district seed). Role names are read from the config/enum mapping, not hard-coded.
- [X] T017A [P] Unit tests for **PRP scrubbing** in `tests/unit/test_prp.py` — given a seed containing PRP-flagged HCPs, assert no `prp = true` HCP appears in any data-access read or retriever result for a field user (FR-020); depends on T008A and the T009 PRP amendment
- [X] T018 [P] Unit tests for the data-access interface + generator in `tests/unit/test_data_access.py` — seeded counts match the required shape; same seed → identical data (repeatability); `synthetic=true`
- [X] T019 [P] Unit tests for schemas in `tests/unit/test_schemas.py` — every recommendation object requires a non-empty `reason`; assembly guard rejects a missing reason

**Checkpoint**: Interface, seeded data, RBAC, provider seams, orchestrator/API skeletons ready and tested. Component work can begin.

---

## Phase 3: User Story 1 — See who to ride with and why (Priority: P1) 🎯 MVP

**Goal**: Brief section 1 — a ranked list of reps needing attention, each with a visible, data-backed reason.

**Independent Test**: `GET /api/reps` as a DM returns a ranked list scoped to the DM's district where every rep carries a reason (signals + weights + data points); a region-level role sees both districts.

### Tests for User Story 1 ⚠️ (write first, ensure they fail)

- [X] T020 [P] [US1] Unit test the **deterministic scorer** in `tests/unit/test_ranking.py` — fixed visible weights applied to the 4 signals, documented stable tie-break, identical seed → identical ranks/scores (no LLM in the path). **Per-brand inputs (I1)**: the "declining share" and "low call activity in key accounts" signals read per-(account, brand) rows from `AccountBrandMetrics`/`CallActivity`; assert the rollup rule — each signal is aggregated across all of the rep's (account, brand) rows into one per-rep value before weighting — so the per-rep score is deterministic.
- [X] T021 [P] [US1] Example-based test in `tests/unit/test_ranking_golden.py` — known seeded District 1 input → ranked rep ids, scores, and `reason` structure match the committed golden fixture (keyed on IDs + Brand enum NAME, independent of the unconfirmed display spelling). **Anti-LLM-ranking guard (FR-002, FR-012)** lives in `tests/unit/test_ranking.py`: snapshot ranks + scores before LLM narration, run narration (mocked LLM), then assert ranks, scores, signal values, and contributors are byte-for-byte identical afterward — the LLM may change only `reason.summary`
- [X] T022 [P] [US1] Explainability test (FR-003) in `tests/unit/test_ranking.py` — every `RepRanking` carries a non-empty structured reason with the four signal contributions and ≥1 top-contributor entry. (The `GET /api/reps` endpoint variant — RBAC-scoped, `limit` honored — is deferred to the API phase, which is out of Phase 3 scope.)
- [X] T022a [P] [US1] **Fairness test** (FR-017) in `tests/unit/test_ranking.py` — perturbing a non-signal attribute (e.g., `tenure_months`) leaves the ranks AND scores unchanged; ranking is influenced only by the four business signals (no protected attributes or proxies)

### Implementation for User Story 1

- [X] T023 [US1] Implement the **deterministic prioritization scoring function** in `src/coach/components/ranking.py` (reads per-(account, brand) metrics through the new RBAC+PRP-scrubbed `get_account_brand_metrics` data-access read) — pure code, fixed visible weights from config over the 4 signals; returns `list[RepRanking]` + `Reason` (signals, weights, contributions, data points). **Per-brand metrics (I1)**: the "declining share" and "low call activity in key accounts" signals read per-(account, brand) rows from `AccountBrandMetrics`/`CallActivity`, then **roll up to a single per-rep value by aggregating across all of the rep's (account, brand) rows** (simple, explicit rule — e.g., volume-weighted share decline and total calls vs. opportunity across the rep's brand rows) before applying weights; the rollup MUST be deterministic so the T021 golden fixture is stable. **The LLM does NOT decide ranking.** Depends on T005, T006, T009
- [X] T024 [US1] Implement LLM **reason narration** (separate step) in `src/coach/llm/narrate.py` — turns the structured `Reason` into clear language via the `LLM` seam in `src/coach/llm/client.py` (minimal `BedrockLLM`, model id from config; the T012 wrapper can extend it), writing ONLY `reason.summary` and never touching ranks/scores/signals/contributors (FR-002, FR-012; enforced by `model_copy` and verified by the anti-LLM-ranking guard). Depends on T023
- [X] T025 [US1] Wire the `prioritize` node into the graph and implement `GET /api/reps` in `src/coach/api/app.py` (audit record emitted). Depends on T015, T016, T023, T024. RBAC-scoped (data-access layer) + `?limit` honored; deterministic ranking in code, LLM narrates only; narrate-before-expose re-checked at the boundary (no `PENDING_*` placeholder may reach a client); one privacy-safe audit record per call

**Checkpoint**: US1 fully functional and independently testable — this is the MVP slice.

---

## Phase 4: User Story 2 — What to coach this rep on (Priority: P2)

**Goal**: Brief section 2 — 1–3 coaching focus areas for the selected rep, each with a reason.

**Independent Test**: For a seeded rep, the brief returns 1–3 focus areas each with a data-tied reason; a rep with no notable gap returns an explicit "no high-priority focus area".

### Tests for User Story 2 ⚠️

- [X] T026 [P] [US2] Component + example-based test in `tests/component/test_coaching_focus.py` — 1–3 focus areas, each with a reason; seeded input → expected focus areas; threshold change shifts selection predictably; explainability (FR-010); anti-LLM guard; no-gap and no-history edge cases handled (FR-018)

### Implementation for User Story 2

- [X] T027 [US2] Implement `coaching_focus` component in `src/coach/components/coaching_focus.py` — deterministic selection of 1–3 focus areas from a config catalog + config trigger thresholds (reads signals via the shared `src/coach/components/signals.py`, through the data-access layer); each focus carries a data-tied `Reason`. LLM only phrases the reason text (`narrate_focus` in `src/coach/llm/narrate.py`, model_copy → summary only). Depends on T005, T006, T023
- [X] T028 [US2] Wire the `coaching_focus` node into the graph and into the brief (section 2) — done in `src/coach/orchestrator/brief_graph.py` (`_coaching_focus_node`). Depends on T015, T027

**Checkpoint**: US1 + US2 both independently functional.

---

## Phase 5: User Story 3 — Ride-along prep (Priority: P2)

**Goal**: Brief section 3 — prior notes, agreed actions, and what to observe next (RAG over coaching notes).

**Independent Test**: For a rep with history, returns last notes + agreed actions + observe-next; for a rep with none, returns an explicit empty state.

### Tests for User Story 3 ⚠️

- [X] T029 [P] [US3] Component test in `tests/component/test_ride_along_prep.py` — deterministic seeded assembly (expected notes / agreed actions / observe-next; most-recent-N from config); retrieval is RBAC-scoped (out-of-scope → `ScopeError`) and PRP-scrubbed (a PRP-tied note + its fields never surfaced); provenance per item (FR-010); anti-LLM guard (only summary/opening change); empty-state for a no-history rep + "not recorded" for a missing field (FR-018)

### Implementation for User Story 3

- [X] T030 [US3] Implement `ride_along_prep` component in `src/coach/components/ride_along_prep.py` — deterministic assembly: prior-note free text via the **`Retriever`** (RBAC + PRP guarded) and `agreed_actions`/`observe_next` via the **structured store**, gated to the same (PRP-scrubbed) session set; most-recent-N from config; per-item provenance; returns `EmptyState` when no surfaceable history. New schemas `RideAlongPrep`/`EmptyState`/`PriorNote`/`PriorActionItem`/`NoteSource`. LLM (`narrate_ride_along`) writes only `reason.summary` + `opening`. Depends on T011, T006
- [X] T031 [US3] Wire the `ride_along_prep` node into the graph and into the brief (section 3) — done in `src/coach/orchestrator/brief_graph.py` (`_ride_along_node`). Depends on T015, T030

**Checkpoint**: US1–US3 independently functional.

---

## Phase 6: User Story 4 — Accounts/HCPs & business context (Priority: P2)

**Goal**: Brief section 4 — key accounts/HCPs with business context and behavior-vs-opportunity mismatch flags.

**Independent Test**: For a seeded rep, returns a focused account list with context (share, volume, performance, spend, calls trend) and at least one mismatch flag where warranted; all in-scope.

### Tests for User Story 4 ⚠️

- [X] T032 [P] [US4] Component + example-based test in `tests/component/test_accounts_context.py` — focused list (not whole book), context fields present, mismatch flagging (low calls on high opportunity), RBAC-scoped, missing-data reported not fabricated. **Per-brand labeling (FR-007, finding N2)**: assert the output is broken down BY BRAND — a seeded account that carries metrics across multiple brands produces one `AccountFocus` per (account, brand), each labeled with its `brand`; assert the (account, brand) rows match the seeded `AccountBrandMetrics` for that account and no per-account collapsing occurs

### Implementation for User Story 4

- [X] T033 [US4] Implement `accounts_context` component in `src/coach/components/accounts_context.py` — deterministic: selects the **focused** key (account, brand) rows (top `accounts_max` from config by a priority of opportunity/risk/share-decline/mismatch), attaches per-(account, brand) business context, and flags **behaviour-vs-opportunity mismatch** (high opportunity + low calls, `mismatch_call_threshold` from config), each with a data-tied `Reason`. **Per-brand (I1/FR-007)**: reads per-(account, brand) rows from `AccountBrandMetrics`/`CallActivity` (RBAC + PRP scrubbed) and produces **one `AccountFocus` per (account, brand)**, labeled by the **Brand enum display name** (no per-account collapsing). Updated schemas: `AccountFocus` now carries `brand` + `AccountBrandContext` (incl. `calls_trend`). LLM (`narrate_account_focus`) writes only `reason.summary`. Edge cases (FR-018): no accounts → empty; missing call activity → "not recorded". Depends on T005, T006, T009
- [X] T034 [US4] Wire the `accounts_context` node into the graph and into the brief (section 4) — done in `src/coach/orchestrator/brief_graph.py` (`_accounts_node`). Depends on T015, T033

**Checkpoint**: US1–US4 independently functional.

---

## Phase 7: User Story 5 — Suggested opener (Priority: P3)

**Goal**: Brief section 5 — a short suggested opener referencing the rep's specifics; the full `/api/brief/{rep_id}` now returns all five sections.

**Independent Test**: For a populated brief, returns a short opener referencing this rep's points, carrying a reason, presented as an editable suggestion.

### Tests for User Story 5 ⚠️

- [X] T035 [P] [US5] Component test in `tests/component/test_opener.py` — deterministic talking-point selection (seed 42, expected source/ref order) + config cap; provenance on every point mirrored in the reason (FR-010); suggestion-only data, no action (FR-011); anti-LLM guard (only `text` + `reason.summary` change; no points added); FR-018 no-priority rep gets the positive default opener, not fabricated

### Implementation for User Story 5

- [X] T036 [US5] Implement `opener` component in `src/coach/components/opener.py` — **deterministic** talking-point selection (pure function of the already-built section outputs — priority reason, coaching focus, accounts/mismatch; introduces no new data, fetches nothing). Selects an ordered, config-capped (`opener_max_points`) set of `TalkingPoint`s (top real coaching focus + key/mismatched account + top priority signal), each with provenance (`source` + `ref`); FR-018 positive default when no high-priority signals. The LLM (`narrate_opener`) writes only the opening `text` + `reason.summary`, rephrasing the given points (no new facts/numbers/brands); suggestion only (FR-011). New schemas: `Opener.talking_points` + `TalkingPoint`/`OpenerSource`. Depends on T006, T023/T027/T033
- [X] T037 [US5] Wire the `opener` node into the graph and implement `GET /api/brief/{rep_id}` (full 5-section brief, RBAC `403` on out-of-scope, audit record) in `src/coach/api/app.py`. Depends on T015, T016, T036, and T028/T031/T034. Calls the orchestrator (`build_brief`) with the caller's `AccessContext` threaded through every node (RBAC + PRP hold; PRP HCPs never appear); out-of-scope AND not-found both return the same `403` (FR-014 — no existence leak); narrate-before-expose re-asserted before returning; one privacy-safe audit record per brief

**Checkpoint**: All five sections of the brief are generated.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Whole-brief quality, UI, audit, and validation.

- [X] T038 Implement the **5-section checklist rubric** e2e test in `tests/e2e/test_brief_rubric.py` — a brief PASSES only if all 5 sections are present AND every recommendation has a visible reason (encodes the fixed rubric via `assembly.rubric_violations`; SC-002). **Consistency check (SC-004)**: run the brief twice for the same seeded DM → identical brief (skeleton + facts + deterministic wording). Plus the **narrate-before-expose guard** (assembly RAISES on a placeholder), **RBAC** (out-of-scope rep → `ScopeError`) + **PRP** (PRP accounts never appear in the brief), and the **FR-018** no-history rep (valid, rubric-passing brief with an `EmptyState` ride-along)
- [X] T039 [P] Implement the minimal web page in `web/index.html` — renders the 5 sections and each `reason` block (suggestions only; DM decides). Read-only single page (served at `GET /` by `src/coach/api/app.py`) that calls ONLY the GET API (`/api/whoami`, `/api/reps`, `/api/brief/{rep_id}`) and renders exactly what the API returns (no client-side ranking/recompute). Shows a seeded-user selector (dm_d1/dm_d2/region_r1/hos_1) → scope chip; the ranked-rep rail with each priority reason; and the full five-section brief with the **`reason` (why + signals + data points)** under every recommendation (FR-010), per-brand account context + mismatch flag, ride-along provenance, and clean empty/`403` states (FR-014/FR-018). Offline demo entrypoint `src/coach/api/demo.py` (`uvicorn coach.api.demo:app`) wires the deterministic offline narrator + fake embeddings + auto-seeded synthetic data so the page renders with no live Bedrock call. Tests in `tests/e2e/test_ui.py` (page served, read-only/GET-only + references only GET endpoints, a non-placeholder reason on every section, the no-history empty state)
- [X] T040 [P] Audit assertions in `tests/e2e/test_audit.py` — one record per brief generation (and per reps list); no out-of-scope data, no raw PII. **Privacy-in-logging (FR-016)**: asserts HR-sensitive rep fields and private HCP fields are never logged (capture the request-path logs and assert rep/HCP names are absent; assert the audit record carries ONLY allow-listed safe fields), and that `build_audit_record` refuses a HR-sensitive field (uses the field-level classification from T014)
- [ ] T041 [P] Synthetic-only guard test in `tests/e2e/test_synthetic_only.py` — every data response carries `synthetic=true`; no real connector is configured (SC-007)
- [ ] T042 End-to-end run of quickstart.md scenarios A–D in `tests/e2e/test_quickstart.py` (happy path, RBAC, empty/sparse, determinism golden)
- [ ] T043 [P] Update `README.md` / docs with run + eval instructions (`/gen-synthetic-data`, `/run-checklist-eval`)

---

## Deferred checks (post-API)

> These depend on API routes that do not exist yet. Add them once the relevant routes
> are implemented — do not lose track of them.

- **F6 — SUPERSEDED → SATISFIED for the read-only MVP API** (was: read-only API guard —
  assert only `GET` routes, no write/mutation path). The current MVP API is **entirely
  read-only**, so this is now asserted directly: `tests/e2e/test_api.py::test_only_get_routes_are_exposed`
  fails if any route exposes a non-GET (POST/PUT/PATCH/DELETE) verb (FR-011, suggestion-only).
  When region-level **write/action** routes are later designed, extend this with per-route
  authorization tests (region roles have full access, not read-only).
- **F7** — Graceful degrade for `GET /api/brief/{rep_id}`: when later sections (US2–US4)
  are not yet wired, the endpoint degrades gracefully instead of failing (US5 independence).
- **F8 — SUPERSEDED → SATISFIED for reads by scope-level route tests** (was: assert an RBD
  `read_only=true` cannot reach a write/action path). Replaced by scope-level **authorization
  tests over the API** in `tests/e2e/test_api.py`: a `district` DM sees only their district
  (`test_dm_reps_are_scoped_to_their_district`), `region`/`all` see wider scopes, an
  out-of-scope `rep_id` is a `403` indistinguishable from not-found (FR-014), and the caller
  **cannot widen their own scope via input** (`test_caller_cannot_widen_scope_via_input`).
  Extend with write/action-route authorization tests when those routes exist.
- **C2 (deferred)** — A dedicated performance-validation task for SC-001 / the ≤10s p95 brief-assembly goal is intentionally deferred for the MVP (no perf test task in scope).

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

---

## Roadmap Phases 7–10 (post-MVP capabilities) — PLANNED, not started

> These are the **roadmap milestones** for capabilities #6/#5/#4/#2 (see *spec.md → Future
> Capabilities* and [`docs/project-status.md`](../../docs/project-status.md)). They are
> **separate from the MVP build-phase numbering (Phases 1–8) above** — that numbering belongs
> to the morning-brief MVP. None of the tasks below is started; each keeps the same
> constitution rules as the MVP (deterministic logic in code; LLM wording only; the single
> data-access door with RBAC + PRP on reads AND writes; a `reason` on everything;
> synthetic-only; suggestion/record-only — the human decides).

### Roadmap Phase 7 — theme aggregation (capability #6)

- [X] P7-T1 Define the **scoped, aggregate-only** leadership view: a deterministic, code-computed roll-up of coaching themes across reps that returns **patterns and counts only — never named individual reps or individually identifiable detail** (FR-016). The LLM may only narrate the `reason`. — `src/coach/components/theme_aggregation.py` (`aggregate_themes`); new `Theme` / `ThemeAggregate` schemas (no rep-identity field — structural privacy); themes come from the SAME `coaching_focus_for_rep` (shared signals + config catalog) so there is no drift; ranked by rep-count desc; each theme carries a `reason` with supporting counts (reps-in-scope / reps-with-theme / share + per-district counts). LLM narration `llm/narrate.py::narrate_theme(s)` (counts/shares only to the LLM; `model_copy` → summary only).
- [X] P7-T2 Enforce **RBAC scope** on the aggregation at the data-access door: only the **region** and **all** scope levels may request it, each only across **their own region / all regions** (no unscoped roll-up). PRP scrubbing still applies to any underlying read. — `_require_leadership_scope` raises `ScopeError` for any scope below region; in-scope reps come from `data.get_reps(ctx)` (region-isolated at the data layer), all reads stay PRP-scrubbed through the data-access layer.
- [X] P7-T3 Tests: the view exposes no individual-rep detail and no out-of-scope data; a `district` caller cannot obtain a cross-rep aggregation. — `tests/component/test_theme_aggregation.py` (11 tests): structural + serialized patterns-only (no rep id/name), DM + self → `ScopeError`, region/all allowed, deterministic golden (seed 42), same-source vs the per-rep section, anti-LLM guard (counts unchanged), explainability, and a 2-region dataset proving region isolation + predictable count changes.

### Roadmap Phase 8 — Summit optimization (capability #5)

- [X] P8-T1 Add the **Summit / IC-plan lift** as a new ranking signal **computed in code** from data + **per-team config** (a per-team formula), normalized and weighted like the four existing signals — **deterministic and explainable; the LLM never scores or decides it**. — `src/coach/components/summit.py`: per-team `SummitFormula` in config (a clearly-labeled **placeholder**, swappable per team without code change), district Summit scores + ranking, and a deterministic **what-if lift** (halt a rep's top declining (account, brand) rows → recompute → "#3 → #1"). New schemas `SummitInsight` / `SummitTarget` + `SignalName.summit_opportunity`. Integrated into the existing normalized rollup in `ranking.py` (`_apply_summit`, gated on `ranking_weights["summit_opportunity"]` > 0 — **OFF by default** so the four-signal MVP ranking is unchanged); raw = lift, normalized 0..1 via the config cap (ADR 0001), each reason carries the targeted movements + the ranking change with raw numbers. LLM narration `llm/narrate.py::narrate_summit` (lift/targets only → the LLM; `model_copy` → summary only). Reads only through the data-access layer (RBAC-scoped + PRP-scrubbed).
- [X] P8-T2 Tests: the Summit signal is deterministic (same data/config → same value); the anti-LLM-ranking guard still holds (narration changes only `reason.summary`); per-team config changes the lift predictably. — `tests/component/test_summit.py` (9 tests): deterministic scores + what-if lift (lifts 2/1/0 on a 3-district set), determinism, **per-team config** (identical inputs + different configured formulas → different scores), formula change scales scores predictably, **rollup integration** (off by default; with a non-zero weight the Summit signal folds in via the normalized rollup — score = four-signal score + normalized contribution), explainability, the **anti-LLM guard**, and **RBAC + PRP** (PRP rows scrubbed; a DM aggregates only their own district).

### Roadmap Phase 9 — covariant analysis (capability #4)

- [ ] P9-T1 Define the **"success" measure** (open question) the covariant analysis is computed against.
- [ ] P9-T2 Implement covariant analysis in the accounts section **in code — deterministic and explainable, NOT LLM-decided**; the LLM only narrates the structured finding; every finding carries a `reason`.
- [ ] P9-T3 Tests: same data → same finding; explainability (a visible reason + the data behind it).

### Roadmap Phase 10 — verbal feedback / CLOSE capture (capability #2)

- [ ] P10-T1 Add the **CLOSE record** (the DM's post-ride observations / development focus), optionally via **Amazon Transcribe** *(planned)*. The assistant **records the human's input — it does not act or auto-generate a plan** (suggestion-only holds).
- [ ] P10-T2 Implement the **first write path** through the **same data-access door** under the **writer's own scope (writer-scope RBAC)**; never a bypass.
- [ ] P10-T3 On **readback**, apply the **same PRP scrubbing + RBAC** as every other note (**ADR 0002** — retriever enforces RBAC + PRP at query time): a CLOSE note that references a PRP HCP is never surfaced to a field user.
- [ ] P10-T4 Tests: write-scope RBAC (a writer cannot write outside their scope); PRP-on-readback (a captured PRP-referencing note is scrubbed); the assistant takes no autonomous action.
