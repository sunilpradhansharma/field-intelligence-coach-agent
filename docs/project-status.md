# Project Status — Field Intelligence Coach Agent

> **Living memory.** This file lets any person — or any new AI session — resume with
> full context. Sections are split into **BUILT** (in the repo now), **DECIDED**
> (confirmed by the stakeholder), and **OPEN** (still pending). Keep it current.
>
> Last updated: 2026-06-12.

---

## 1. Project summary

The Field Intelligence Coach Agent helps **district managers (DMs)** prepare to coach
their sales reps and decide where to spend limited field time. Today that coaching is
inconsistent and field time is often split "equally" rather than "fairly." The agent's
goal is to shift field time from *equal* to *fair* and to raise overall coaching
quality, while keeping the human in charge: the agent only **suggests**, the DM always
**decides**. The MVP is the **"morning coaching brief"** — one short, explainable brief
a DM reads before a field ride: who to ride with and why, what to coach, what happened
last time, which accounts/HCPs matter and how the business is doing, and a suggested
opener. Every recommendation shows its reason and the data behind it, and all data is
synthetic.

---

## 2. Current status — BUILT (in the repo now)

**Phases 1–10 are COMPLETE and tested — ALL SIX original capabilities are now built end to
end.** The MVP (the morning coaching brief, Phases 1–6) runs end to end (synthetic data →
RBAC/PRP data-access layer → deterministic ranking → the five brief sections → the orchestrated,
narrated, validated brief → the read-only API → the read-only web UI), and the four post-MVP
capabilities are built: **#6 theme aggregation (Phase 7), #5 Summit optimization (Phase 8),
#4 covariant analysis (Phase 9), and #2 verbal feedback / CLOSE capture (Phase 10 — both Step 10a
the text write path AND Step 10b voice capture)**. `pytest` → **215 passed**. What remains is
**productionization** (real data connectors, auth, UI polish/hardening) and confirming the
labeled assumptions with the business — not new capabilities (§5, §7).

**All six original capabilities, end to end:** (1) prioritize who to ride with + **why**;
(2) coaching focus **+ verbal feedback / CLOSE capture**; (3) ride-along prep; (4) business
outcomes **+ covariant analysis**; (5) **Summit optimization**; (6) **theme aggregation**.

### Code (`src/coach/`)
- **Data-access interface** — `src/coach/data_access/interface.py`: `DataAccess` and
  `Retriever` Protocols, `AccessContext`, and `ScopeError`. Every component reads
  through this seam (built first; task **T005**).
- **Pydantic schemas** — `src/coach/schemas.py`: entities (`Region`, `District`, `User`,
  `Rep`, `Account`, `CallActivity`, `CoachingSession`), the explainability `Reason`
  object (`SignalContribution`, `DataPoint`), recommendation objects (`RepRanking`,
  `CoachingFocus`, `AccountFocus`, `Opener`, `CoachingBrief`-related), and the `Dataset`
  container (task **T006**).
- **SQLite store** — `src/coach/data_access/sqlite_store.py`: structured store behind the
  interface, labeled `synthetic=true` (task **T007**).
- **Config** — `src/coach/config/settings.py`: reads `BEDROCK_MODEL_ID`, `AWS_REGION`,
  `BEDROCK_EMBED_MODEL_ID`, `COACH_DB_PATH`, `COACH_SEED`, and the fixed ranking weights
  from env/config. The model id is **never** hard-coded (task **T004**).
- **Seeded synthetic generator** — `src/coach/synthetic/generate.py`: deterministic from
  a fixed seed. 1 region, 2 districts, 1 DM + 8–12 reps each, 15–30 accounts/HCPs/rep,
  2–3 coaching sessions (some reps 0, an edge case), with the four ranking signals made
  to vary across reps (task **T009**).

### Recent amendment (BUILT) — task **T007A** + the **T009** generator amendment
- **`Brand` enum** (`schemas.py`) — single source of truth for brand names. No brand
  string literals exist anywhere else in the source (confirmed by review).
- **`prp` flag** — `Account.prp: bool` added to the schema and the `accounts` table.
  PRP data was *added* here in Phase 1; **scrubbing is now built in Phase 2** (task
  **T008A**, see below).
- **Per-(account, brand) metrics** — new `AccountBrandMetrics` model and
  `account_brand_metrics` table keyed by `(account_id, brand)`; `brand` added to
  `CallActivity`. This is the I1 decision (metrics are per brand).
- **Generator amendment** — ~8% of HCPs are flagged PRP (with a deterministic guarantee
  that at least one always exists), and per-(account, brand) metrics + per-brand call
  activity are generated across all five brands, drawn only from the `Brand` enum.

### Phase 2 (BUILT) — RBAC + PRP enforcement — tasks **T008, T008A, T017, T017A**
- **Scope-level RBAC** (`src/coach/data_access/rbac.py`, enforced inside every
  `sqlite_store` read — Principle V / FR-013): access is scoped by **level**, not job
  title — `self` (rep → own records), `district` (DM → own district), `region` (RD/RBE →
  whole region), `all` (Head of Sales → all regions). All non-rep roles have **full
  access** (no read-only). An out-of-scope read raises **`ScopeError`** at the data-access
  layer (not the UI).
- **Single config source** — the role → scope-level mapping lives only in
  `config.settings.ROLE_SCOPE_LEVELS` (`scope_level_for()`); no role names are hard-coded
  in enforcement logic. `AccessContext` carries a `scope_level` derived from the role; the
  legacy `read_only` flag was removed.
- **PRP scrubbing on every read** (T008A / FR-020): HCPs flagged `prp = true` are dropped
  before any result is returned, at every scope level — `get_accounts` (`prp = 0`),
  `get_call_activity` (excludes activity tied to PRP accounts — the subtle leak path),
  and `get_business_metrics` (inherits via `get_accounts`). The vector-store retriever is
  **not built**; `rbac.py` documents the hook that it must reuse `prp_account_ids()` to
  scrub PRP when built (T011).
- **Seeded users** (`generate.py`): `dm_d1`, `dm_d2` (district), `region_r1` (RD/region),
  `hos_1` (Head of Sales/all) — so all four scope levels are testable.
- **Hardening applied**: `get_rep` now checks scope **before** revealing existence, so an
  out-of-scope caller cannot distinguish "rep exists elsewhere" from "rep does not exist"
  (both raise `ScopeError`) — **FR-014**. A `# TODO(T008A)` marker sits on the
  `account_brand_metrics` access point so the **Phase 4** per-brand accounts read (FR-007)
  applies the same PRP scrub.

### Phase 3 (BUILT) — deterministic ranking — tasks **T020, T021, T022, T022a, T023, T024**
- **Deterministic scorer** (`src/coach/components/ranking.py`, FR-002/FR-012): pure code,
  no LLM in the path. For each in-scope rep it reads per-(account, brand) metrics, call
  activity, and coaching sessions **through the data-access layer** (already RBAC-scoped +
  PRP-scrubbed — added the `get_account_brand_metrics` read with the same scope + PRP
  scrub), rolls the four signals up to one value per rep, and produces `RepRanking`s.
  Tie-break = total desc, opportunity_risk desc, rep_id asc (documented, stable).
- **Signal normalization (so config weights control influence)**: each signal's raw
  aggregate is mapped to **0..1** before weighting — `normalized = min(raw, cap) / cap` —
  using a single, visible config basis `Settings.ranking_norm_caps` (defaults: declining
  share **3.0**, low call activity **10**, missed follow-up **3**, opportunity/risk **10**;
  a value at/above its cap saturates to 1.0). `score = Σ(normalized × weight)` with weights
  from `ranking_weights`. Because every signal shares the 0..1 scale, the **fixed weights
  alone** control relative influence — a count-style signal can no longer swamp a fractional
  one. (Scores are now in 0..1; this reordered the two top District-1 reps, and the golden
  fixture was regenerated.)
- **Reason shows raw + normalized**: `SignalContribution` now carries **both** `raw_value`
  (the real aggregate the DM sees) and `normalized_value` (0..1, used in scoring), plus
  `weight` and `contribution = normalized × weight`. The stale "normalized 0..1" docstring
  on `raw_value` was **corrected** to describe the real raw aggregate. Top-contributor
  `DataPoint`s still show real per-(account, brand) figures (share_trend, calls, perf),
  keyed on the Brand **enum name** (not the unconfirmed display spelling).
- **LLM kept out of ranking** (`src/coach/llm/narrate.py` + `client.py`): narration takes an
  already-computed `RepRanking` and rebuilds it with `model_copy` so **only**
  `reason.summary` can change — ranks, scores, signal values, and contributors are preserved
  by construction. Model id from config (`BEDROCK_MODEL_ID`), never hard-coded; boto3 is
  lazy; tests inject a fake LLM (no live Bedrock calls). Until narrated, `summary` holds the
  `PENDING_SUMMARY` placeholder (see Phase 5 requirement in §5).

### Phase 4 (COMPLETE) — brief sections, built one at a time
**Section 1 of 4 — coaching focus (FR-005) — tasks T026, T027 — DONE.**
- **Deterministic focus selection** (`src/coach/components/coaching_focus.py`): the focus
  areas are decided in **pure code**, not by the LLM. A signal triggers a focus when its raw
  value clears a **config-visible trigger threshold** (`Settings.focus_thresholds`); the
  focus wording comes from a **config-visible catalog** (`Settings.focus_catalog`). The top
  1–3 are returned, ordered by **strength** (the **normalized 0..1** value, same basis as
  ranking — ADR 0001) then the fixed signal order (deterministic tie-break).
- **Structured reasons with real data** (FR-010): each `CoachingFocus` carries the triggering
  `SignalContribution` (raw + normalized) plus real data points — the per-(account, brand)
  rows or coaching sessions behind it (keyed on the Brand enum name).
- **Edge cases, no fabrication** (FR-018): a rep with no signal above threshold gets a single
  low-priority **default focus** with a clear note; a **no-history** rep is handled gracefully
  (missed-follow-up can't trigger; the default note states "no prior coaching history yet").
- **LLM limited to wording**: `narrate_focus` (`src/coach/llm/narrate.py`) rebuilds via
  `model_copy` so only `reason.summary` changes — `focus_area`, signals, and data points are
  preserved by construction (anti-LLM guard test verifies it). Model id from config; fake LLM
  in tests.

**Shared rollup refactor** (`src/coach/components/signals.py`): the per-rep signal
computation was extracted into one place. **Ranking and coaching focus now share the same
rollup**, so their signal numbers can never drift apart. Ranking output was verified
**unchanged** (the T021 golden fixture is the guard and is green).

**Section 2 of 4 — ride-along prep — DONE.** Step 2a (the notes retriever **seam**, T010/T011)
and Step 2b (the `ride_along_prep` **component**, T029/T030) are both complete.
- **Step 2a — notes retriever seam — tasks T010, T011 — DONE.**
  - **Embeddings behind an interface** (`src/coach/llm/embeddings.py`): an `EmbeddingProvider`
    Protocol with a **lazy `BedrockEmbeddings`** (Amazon Titan, **model id from config**, boto3
    imported on first use) and a deterministic **`FakeEmbeddings`** for offline tests.
  - **Vector store behind an interface** (`src/coach/data_access/vector_store.py`): a
    `VectorStore` Protocol with an **in-memory cosine store** for the MVP (offline, repeatable;
    the in-memory option used in tests) → maps to a Chroma / managed backend in production.
  - **The retriever is part of the single door, not a bypass**
    (`src/coach/data_access/notes_retriever.py`): `NotesRetriever.search_notes` is the single
    guarded entry point and enforces the **same RBAC scope + PRP scrubbing as the structured
    store** — it **reuses the existing helpers** (`rbac.require_rep_in_scope` for scope →
    `ScopeError` out of scope, and `rbac.prp_account_ids` to drop any note tied to a PRP-flagged
    account), rather than reimplementing the rules. Each note is tied to the account/HCP it
    concerns as **index metadata only** (no `CoachingSession` schema change — the existing
    free-text `notes_text` is indexed, so no seeded note field was added and no count/golden
    test needed updating). Retrieval is **synthetic-only and seeded/repeatable** (FakeEmbeddings
    + fixed seed → same notes every run). Rationale: **ADR 0002**.
- **Step 2b — `ride_along_prep` component — tasks T029, T030 — DONE**
  (`src/coach/components/ride_along_prep.py`, FR-006/FR-010/FR-018):
  - **Deterministic assembly, facts decided in code**: surfaces the rep's prior coaching for
    the pre-ride conversation — **prior-note free text via the RETRIEVER** (the RBAC + PRP
    guarded path) and **agreed actions + what-to-observe-next from the STRUCTURED store**. The
    **most-recent-N** limit comes from config (`Settings.ride_along_max_notes`). New schemas:
    `RideAlongPrep` / `EmptyState` / `PriorNote` / `PriorActionItem` / `NoteSource`.
  - **Provenance on every item** (FR-010): each surfaced note/action records its `session_id`,
    `date`, and `source` (**structured store vs retriever**); the `reason` documents both data
    sources. Nothing is surfaced without provenance.
  - **RBAC + PRP preserved**: both reads pass the caller's `AccessContext` and never widen
    scope (out-of-scope rep → `ScopeError`). The structured `agreed_actions`/`observe_next` are
    **gated to the same session set the retriever returns**, so a **PRP-tied note and its
    structured fields are never surfaced** (the subtle leak is closed).
  - **Edge cases, no fabrication** (FR-018): a **no-history** rep returns a clean `EmptyState`
    ("No prior coaching history yet."); a rep whose only notes are PRP-restricted also returns
    `EmptyState`; a missing field (e.g. empty observe-next) yields a clear **"not recorded"**
    note rather than being dropped or invented.
  - **LLM limited to wording**: `narrate_ride_along` (`src/coach/llm/narrate.py`) rebuilds via
    `model_copy` so only `reason.summary` and the `opening` suggestion change — the facts
    (notes, agreed actions, observe-next, provenance, empty-state message) are preserved by
    construction (anti-LLM guard test verifies it). Model id from config; fake LLM in tests.

**Section 3 of 4 — accounts + per-brand business context — tasks T032, T033 — DONE**
(`src/coach/components/accounts_context.py`, FR-007/FR-008/FR-010/FR-018):
- **Focused selection, decided in code**: surfaces a **focused list of key (account, brand)
  rows** — not the rep's whole book — chosen by a deterministic config rule/cap
  (`Settings.accounts_max`, priority = opportunity + risk + share-decline + mismatch, with a
  documented tie-break). The LLM never chooses or reorders accounts.
- **Per-brand, labeled by the enum** (FR-007 / I1): **one `AccountFocus` per (account, brand)**
  — no per-account collapsing — labeled by the **Brand enum DISPLAY name** (e.g. **LILETTA**
  renders correctly; no brand strings hard-coded). Each carries the per-brand business context
  (market_share, share_trend, volume, spend, performance, opportunity, calls, calls_trend).
- **Mismatch flag in code** (FR-008): the behaviour-vs-opportunity flag (high opportunity +
  low calls, `Settings.mismatch_call_threshold`) is computed deterministically and carries its
  own reason; the LLM cannot set or alter it.
- **RBAC + PRP preserved**: reads **only** through `get_account_brand_metrics` and
  `get_call_activity` (both RBAC-scoped + PRP-scrubbed), passing the `AccessContext` — so an
  out-of-scope rep → `ScopeError` and **PRP-flagged accounts never appear**.
- **Structured reason on every item** (FR-010); **edge cases without fabrication** (FR-018):
  no accounts → empty list; a missing call-activity row → `calls = 0` + a clear "not recorded"
  note.
- **LLM limited to wording**: `narrate_account_focus` (`src/coach/llm/narrate.py`) rebuilds via
  `model_copy` so only `reason.summary` changes — brand, context metrics, mismatch flag, and
  data points are preserved by construction (anti-LLM guard test verifies it).
- New/updated schemas: `AccountFocus` now carries `brand` + `AccountBrandContext` (the I1
  per-(account, brand) shape, incl. `calls_trend`); `test_schemas.py` updated to match.

**Section 4 of 4 — opener — tasks T035, T036 — DONE** (`src/coach/components/opener.py`,
FR-009/FR-010/FR-011/FR-018):
- **Built FROM the already-computed sections, no new data**: `build_opener` is a **pure
  function** of the upstream outputs (the rep's **priority reason**, **coaching focus**, and
  **accounts/mismatch**) — it reads nothing from the store or retriever and introduces no new
  data.
- **Talking points selected in code**: an ordered, **config-capped** (`opener_max_points`)
  set of `TalkingPoint`s — top real coaching focus + the key/mismatched account (labeled by
  the Brand display name) + the rep's top priority signal. The LLM does **not** choose, add,
  drop, or reorder them.
- **Provenance on every point** (FR-010): each `TalkingPoint` records its `source` (priority /
  coaching_focus / account_mismatch / default) and a `ref` back to the exact input, mirrored
  in the opener's `reason.data_points`.
- **LLM phrases the opening line only**: `narrate_opener` rebuilds via `model_copy` so only
  the opening `text` + `reason.summary` change — the talking points and provenance are
  preserved by construction, so the LLM **adds no new facts/numbers/brands** (anti-LLM guard
  verifies it). Suggestion-only — pure data, no action path (FR-011). Model id from config;
  fake LLM in tests.
- **Edge case (FR-018)**: a rep with no high-priority signals (default focus, no flagged
  account, no signals) gets a **positive default opener** (`DEFAULT_OPENER_POINT` from config),
  never fabricated.
- New schemas: `Opener` now carries `talking_points`; added `TalkingPoint` + `OpenerSource`.

**Phase 4 (all five brief sections) is COMPLETE:**
1. ✅ Rep ranking + reason (Phase 3) — who to ride with and why.
2. ✅ Coaching focus (T026/T027) — what to coach.
3. ✅ Ride-along prep (T010/T011 + T029/T030) — what happened last time.
4. ✅ Accounts + per-brand business context (T032/T033) — which accounts matter (brand-labeled).
5. ✅ Opener (T035/T036) — how to open the conversation.

**Production mapping:** local in-memory store + Titan embeddings → **Amazon Bedrock Knowledge
Bases / OpenSearch** behind the same `EmbeddingProvider` / `VectorStore` / `Retriever`
interfaces; the **same query-time RBAC + PRP filter must be re-applied** there (ADR 0002).

### Phase 5 (COMPLETE) — assembly + rubric + API
**Step 5a — orchestrator + brief assembly + rubric — tasks T015, T028, T031, T034, T038 — DONE**
(`src/coach/orchestrator/brief_graph.py` + `assembly.py`, FR-001/FR-010/FR-011; ADR 0003):
- **Fixed, deterministic LangGraph DAG — not an agentic loop**: the graph is built **once**
  with **static edges** (rank → select_rep → **{coaching_focus, ride_along_prep, accounts} in
  parallel** → opener (joins focus + accounts) → assemble). No cycles, no conditional routing,
  no node re-plans; same seed + deterministic LLM → the **same brief**.
- **AccessContext threaded through every node**: each node calls its section component with the
  caller's `AccessContext` and never widens scope — RBAC + PRP hold for the whole brief (an
  out-of-scope `rep_id` → `ScopeError`; PRP accounts never appear in the assembled brief). The
  orchestrator never reads the store/retriever directly.
- **LLM still only narrates**: each node runs the section's deterministic build **then** its
  `narrate_*` (wording only, via `model_copy`). The brief default-selects the **top-ranked**
  rep, or an explicit in-scope `rep_id`.
- **Narrate-before-expose enforced in assembly**: `assemble` builds the `CoachingBrief`, then
  `assert_narrated` **RAISES** (`BriefNotNarratedError`) if any section still holds a
  `PENDING_SUMMARY` / `PENDING_TEXT` / `PENDING_OPENING` placeholder — an un-narrated brief can
  never be returned.
- **Suggestion-only**: the assembled `CoachingBrief` is **pure data** — no action/mutation/
  execute path (FR-011); assembly only builds + validates the object.
- New schemas `CoachingBrief` + `GeneratedFor`; config `ranked_reps_max`.

**Step 5b — read-only FastAPI API — tasks T014, T016, T025, T037, T040 — DONE**
(`src/coach/api/app.py` + `src/coach/observability/audit.py`, FR-001/FR-011/FR-013/FR-014/FR-016):
- **Read surface over the orchestrator** — the reads are all `GET`:
  `GET /api/whoami` (the resolved role + scope), `GET /api/reps?limit=N` (section 1, ranked +
  narrated), `GET /api/brief/{rep_id}` (the full five-section brief via `build_brief`), plus the
  served `/` page. The brief itself is pure suggestion data (FR-011) — no action/mutation path.
  Two capability routes were added (both RBAC-enforced at the data-access layer):
  **`GET /api/themes`** (leadership-scoped — region/all only; a DM gets the same `403` as any
  out-of-scope caller; patterns/counts only, never named individuals), and the **one API write**,
  **`POST /api/brief/{rep_id}/close`** (writer-scope RBAC, reuses the single-door
  `save_close_record`; the observations are the DM's verbatim words). There is no other write path.
- **Identity → role → `AccessContext`, server-side** — the `X-User-Id` header is resolved to a
  `User` via the data-access layer (`SqliteStore.get_user`), and the **`scope_level` is derived
  from the role through the single config source** (`ROLE_SCOPE_LEVELS` / `scope_level_for`). The
  **caller cannot choose their own scope or rep set** — there is no scope/territory input
  (a `?scope_level=…` query string is ignored). Unknown/missing identity → `401`.
- **Per-request DB connection at the data-access boundary** — a fresh store (its own connection)
  is opened per request via a FastAPI dependency and closed when the request ends; no
  process-wide shared connection. Inside the store this is a **small per-thread connection pool**
  (each parallel section read gets its own connection), which also fixed a latent concurrency
  race the single shared connection had under the orchestrator's parallel nodes. Maps to a
  **connection pool / Aurora** in production. RBAC + PRP still run on **every** read regardless of
  which connection executes it.
- **RBAC holds through the API, existence never leaked** — an out-of-scope rep and a
  non-existent rep **both** return the **same clean `403`** with the **same body**
  (`ScopeError` and the in-scope-missing `KeyError` map to one `{"detail": "forbidden"}`),
  so the API cannot reveal whether a rep exists elsewhere (FR-014). The generic error path
  returns a bare `500` with no message or stack trace.
- **PRP never in any response** — PRP HCPs are scrubbed at the data-access layer (the API never
  reads the store directly), verified at both `district` and `all` scope.
- **Narrate-before-expose holds through the API** — the brief path re-asserts `assert_narrated`
  and the reps path re-checks the ranking summaries at the boundary, so **no `PENDING_*`
  placeholder can ever reach a client** (an un-narrated path becomes a clean `500`, not leaked
  placeholder text).
- **Privacy-safe logging (F3 / FR-016)** — `observability/audit.py` records the field-level data
  classification (rep fields = HR-sensitive; HCP fields = private) and a `build_audit_record`
  that emits **only an allow-list of safe identifiers/metadata** (ids, role, scope level, counts)
  and **REFUSES (raises) any HR-sensitive / private field by construction**. One privacy-safe
  audit record per request; rep/HCP names and raw PII are never logged or serialized.
- **Offline-testable, config-driven** — the LLM + embeddings are injected via `AppDeps`, so tests
  run fully offline with fakes; production uses Bedrock behind a lazy seam (model id from config,
  never hard-coded), and `app = create_app()` imports without AWS credentials.
- **Offline-vs-Bedrock factory** (`src/coach/llm/factory.py` — `make_llm` / `make_embedder` /
  `OfflineLLM`) — the server runs **FULLY OFFLINE by default** (a deterministic narrator + embedder)
  and uses **Bedrock only when a model id is configured** (model id from config, never hard-coded).
- **Schema-version guard** — the SQLite store stamps `PRAGMA user_version = SCHEMA_VERSION` on
  generation and the API **verifies it at startup**, so a stale on-disk DB **fails fast** with a
  clear "regenerate with `--seed 42`" message rather than serving against an incompatible schema.

### Phase 6 (COMPLETE) — the read-only web UI — task T039
(`web/index.html`, served at `GET /` by `src/coach/api/app.py`; FR-010/FR-011/FR-014/FR-018):
- **A minimal single page** — vanilla HTML/CSS/JS (no framework), served same-origin
  by the FastAPI app so it shares the API with no CORS. The morning brief is read-only
  (suggestion-only, FR-011); the page now also surfaces the post-MVP capabilities and the one
  write panel (below). The served page at "/" includes (a) the **morning brief with Summit as a
  5th ranking contributor** (`summit_opportunity`) and the **covariant insight in the Accounts &
  business section**; (b) a **role-gated "Leadership themes" view** (region/all only — patterns
  and counts only, never named individuals); and (c) a **"Record close" panel** that writes a
  CLOSE note appearing in the next brief's ride-along prep.
- **The viewer acts as a seeded user, not a scope** — a selector of `dm_d1` / `dm_d2` /
  `region_r1` / `hos_1` sets the `X-User-Id`; the **API derives role → scope** and enforces it.
  The UI never sets or widens scope; a scope chip shows the role + territory from `/api/whoami`.
- **Section 1 rail** — the ranked reps for the caller's scope, each with its **priority reason**.
  Opening a rep loads the **full five-section brief**: priority/why (signals as bars with
  raw/weight/contribution + data points), coaching focus, ride-along prep (prior notes / agreed
  actions / observe-next, **each with provenance**), accounts + **per-(account, brand) context**
  (share, trend, volume, spend, perf, opp, calls, calls-trend) with the **mismatch flag** and
  **brand labels (e.g. LILETTA)**, and the suggested opener (line + talking points).
- **Shows the REASON under every recommendation (FR-010)** — one reusable reason block (the
  "why" + signals + data points) is rendered for all five sections; tested to carry a
  non-placeholder reason on each.
- **Renders only what the API returns** — the browser does **no business logic, ranking, scoring,
  or re-ordering**; it displays the API's `rank` / `total_score` / lists as-is (no client-side
  `sort`, no score math).
- **Clean edge / `403` states** — an out-of-scope (or non-existent) rep surfaces a neutral
  **"Not available in your scope"** message that **never reveals whether the rep exists**
  (FR-014; the API returns the same `403` for both and the UI never reads the body); the
  no-history rep shows the API's empty-state message and missing metrics render "—", never a
  fabricated value (FR-018).
- **Offline demo entrypoint** — `src/coach/api/demo.py` (`uvicorn coach.api.demo:app`) wires a
  deterministic **wording-only** narrator + offline embeddings + auto-seeded synthetic data, so
  the whole page renders end to end **with no live Bedrock call** (verified over HTTP). The
  narrator phrases the already-computed structured reason — it never ranks, scores, or invents
  numbers (Principle I/VI/VIII).

### Phase 7 (COMPLETE) — theme aggregation (capability #6) — tasks P7-T1, P7-T2, P7-T3
(`src/coach/components/theme_aggregation.py`, FR-013/FR-014/FR-016; the first post-MVP capability):
- **Deterministic roll-up from the SAME shared signals — no drift.** For each in-scope rep it
  reuses `coaching_focus_for_rep` (which uses the shared `compute_rep_signals` + the config focus
  catalog), then counts reps per focus area — so a "theme" *is* a per-rep coaching focus, not a
  second drifting definition. Themes are ranked by rep-count (stable tie-break). All grouping,
  counting, and ordering is pure code; a test asserts the aggregate equals an independent per-rep
  tally, and that every theme label is a real catalog entry.
- **Patterns / counts ONLY — never named individuals (FR-016), enforced STRUCTURALLY.** The new
  `Theme` / `ThemeAggregate` schemas have **no rep-identity field** (no `rep_id` / `name`), so an
  aggregated theme cannot carry an individual; the code only ever writes counts (reps-in-scope /
  reps-with-theme / share + per-district counts) into the reason. Verified by a **substring**
  privacy test (no seeded rep id or name appears anywhere in the serialized output, nor in the
  LLM input).
- **RBAC-scoped to leadership.** Aggregation is **region / all only** — `_require_leadership_scope`
  raises `ScopeError` for any scope below region, so a **DM (district) or a rep (self) is
  rejected** (a `403`, indistinguishable from not-found, over the API). Region isolation is real:
  the in-scope reps come from `data.get_reps(ctx)` (region-filtered at the data layer), so a
  region caller can never aggregate another region (proved with a 2-region dataset).
- **Small-cell suppression (privacy).** A new **config-visible, tunable threshold**
  `Settings.aggregation_min_cell` (default 3, env `COACH_AGGREGATION_MIN_CELL`) suppresses any
  grouping cell — a theme's total **or** a per-district count — below the threshold: it is masked
  ("fewer than N (suppressed)" / a "<N each" marker), **never shown as a raw small count**, so a
  small group (e.g. a 1-rep district) can't identify an individual. The scope total is never a
  small cell. Suppressed cells mask `rep_count` / `rep_share` to `None` and set `suppressed=True`.
- **LLM limited to wording.** `narrate_theme(s)` is handed **counts / shares only** (no rep
  identity) and rewrites only `reason.summary` via `model_copy`; an **anti-LLM guard** asserts the
  theme label, signal, counts, shares, and data points are byte-for-byte unchanged. Model id from
  config; FakeLLM in tests; no live Bedrock.
- **Explainability.** Every theme carries a structured `reason` with its supporting counts
  (FR-010). New schemas `Theme` + `ThemeAggregate`; `Settings.aggregation_min_cell`.
- **Surfaced in the UI + API.** A **role-gated "Leadership themes" view** on the served `/` page
  (region/all only — patterns/counts only, never named individuals) renders these themes, backed by
  **`GET /api/themes`** (leadership-scoped; a DM gets the same `403` as any out-of-scope caller).

### Phase 8 (COMPLETE) — Summit optimization (capability #5) — tasks P8-T1, P8-T2
(`src/coach/components/summit.py`, FR-002/FR-012/FR-013/FR-020; ADR 0001):
- **Per-team Summit formula in config — a labeled PLACEHOLDER, swappable without code change.**
  `Settings.summit_formulas` holds a `SummitFormula` per team (= district), resolved by
  `_formula_for`; the engine reads coefficients from config and **never hard-codes a team's
  numbers**. The coefficients are documented as a **representative placeholder** (the business
  will supply the real per-team IC-plan logic — an assumption to confirm), overridable per team
  config-only.
- **What-if ranking lift computed deterministically in code.** Each district gets a Summit score
  from its aggregated (account, brand) inputs; districts are ranked. For a rep, the engine models
  reducing their top declining rows, recomputes the district score, re-ranks, and reports the
  **lift** (e.g. position #3 → #1). Pure integer-position arithmetic — the LLM is never involved.
- **Tunable recovery assumption (per-team config).** How much of a halted decline is assumed to
  come back is **`SummitFormula.recovery_fraction`** (default **1.0** = full recovery, the prior
  behavior; env-overridable `COACH_SUMMIT_RECOVERY_FRACTION`). It scales the score rise and each
  target's projected trend, so a more conservative per-team value is config-only.
- **Integrated as a normalized signal in the shared rollup (ADR 0001).** `ranking.py::_apply_summit`
  folds the lift in via the SAME mechanism as the four core signals — raw = lift, normalized 0..1
  via the config cap, contribution = normalized × the config weight — so config weights stay
  meaningful (no parallel scoring path). **ENABLED by default** with a non-zero weight
  (`ranking_weights["summit_opportunity"]` = **0.2**, tunable via config / env
  `COACH_WEIGHT_SUMMIT`; can still be set to **0** to turn it off), so Summit shows as a **5th
  ranking contributor** (`summit_opportunity`) in every rep's Priority reason. The per-team formula
  and `recovery_fraction` remain labeled placeholder assumptions to confirm.
- **A reason on every Summit insight (FR-010).** Each `SummitInsight` carries a structured reason
  with the targeted **(account, brand) movements** (current → projected trend, decline reduced) and
  the **estimated ranking change** (baseline → projected position, lift), with the raw numbers.
- **LLM limited to wording.** `narrate_summit` is handed the lift/targets only and rewrites only
  `reason.summary` via `model_copy`; an **anti-LLM guard** asserts the lift, targets, positions, and
  data points are byte-for-byte unchanged. Reads go **only through the data-access layer** (RBAC
  scope + PRP scrubbing hold — PRP rows never enter the aggregation or targets). New schemas
  `SummitInsight` + `SummitTarget`, `SignalName.summit_opportunity`; config `SummitFormula` +
  `summit_formulas` + `summit_max_targets` + the Summit weight/cap.
- **Surfaced in the brief + UI.** Summit is folded into the normalized ranking rollup with a
  non-zero default weight and shows as a **5th contributor (`summit_opportunity`)** in every rep's
  Priority reason on the served `/` page.

### Phase 9 (COMPLETE) — covariant analysis (capability #4) — tasks P9-T1, P9-T2, P9-T3
(`src/coach/components/covariant.py`, FR-002/FR-010/FR-012/FR-018; ADR 0001-style transparency):
- **Config-driven "success" measure — a clearly-labeled, tunable ASSUMPTION to confirm.**
  `config.settings.SuccessMeasure` (default: a (account, brand) "wins" if its share is **rising**
  and performance is **on/above target**). It is the single visible definition via
  `meets_success_measure(...)`; the engine never hard-codes a hidden criterion, and the measure is
  tunable per config (env-overridable) — to be confirmed with the business (§5).
- **Transparent, deterministic association computed in code — not a black-box model, not
  LLM-decided.** Across the caller's in-scope (account, brand) rows it computes, as plain
  counts/rates/lift, each behavior variable's success rate **high vs low** and the **optimal
  blend** (the variable combination with the highest observed success rate, with a min-support).
  Two variables, reused with no drift (`call_activity` = calls above `low_call_threshold`;
  `spend_support` = spend ≥ `covariant_spend_threshold`, a placeholder) and disjoint from the
  success measure (no leakage). Fully inspectable; no statistical/opaque model.
- **Insufficient data handled honestly (FR-018).** Below `covariant_min_rows` it returns a clear
  **insufficient-data** state — no optimal blend, no variable findings, an explicit reason — and
  never fabricates an association. The output states plainly it is a simple association on
  **synthetic** data; a richer covariant model needs real data (honesty in the output, not just
  comments).
- **Surfaces in the accounts / business-context section** as a `CovariantAnalysis` with a
  structured `reason` carrying the variables, the success measure used, and the supporting numbers
  (FR-010). **LLM limited to wording** — `narrate_covariant` is handed the findings only and
  rewrites only `reason.summary` via `model_copy` (anti-LLM guard asserts the variables, findings,
  blend, and data points are byte-for-byte unchanged). Reads go **only through the data-access
  layer** (reusing `compute_rep_signals`; RBAC + PRP hold — PRP rows never enter the analysis).
  New schemas `CovariantAnalysis` / `CovariantVariableFinding` / `CovariantBlend`; config
  `SuccessMeasure` + the covariant thresholds.
- **Surfaced in the brief + UI.** The covariant insight is wired into the live brief and renders
  in the **Accounts & business section** on the served `/` page.

### Phase 10 (COMPLETE) — verbal feedback / CLOSE capture (capability #2)
**Step 10a — the CLOSE write path (text) — tasks P10-T1…P10-T4 — DONE**
(`CloseRecord` + `DataAccess.save_close_record`, FR-011/FR-013/FR-014/FR-020; **ADR 0002**):
- **The first WRITE path, through the single door with writer-scope RBAC.** `save_close_record`
  is a method on the data-access layer (not a bypass); `require_rep_in_scope` runs **before** any
  write (reusing the existing scope helper), so a caller may write a CLOSE record ONLY for a rep
  in their own scope. An out-of-scope **or** non-existent rep raises the same `ScopeError`
  (indistinguishable from not-found), exactly like a read. `region`/`all` writers within scope
  succeed. The author identity/scope is **stamped from the authenticated context** (cannot be
  spoofed).
- **`CloseRecord` schema** — rep_id, a **collision-free** unique `session_id` (defaults to a fresh
  id so two records can never overwrite / cross-contaminate; injectable for tests), date,
  observations (non-empty), agreed_actions, observe_next, optional `account_id` (the HCP discussed,
  for PRP on readback), and the stamped author. Malformed records are rejected (validation).
- **The loop closes.** A saved record is persisted as a coaching note in the **same
  `coaching_sessions` table the readback reads** (no second path), so the next **ride-along prep**
  surfaces its observations, agreed actions, and observe-next via the normal scoped + PRP-scrubbed
  read. A new nullable `account_id` column on `coaching_sessions` / `CoachingSession` carries the
  PRP tie (NULL for seed notes — the retriever's positional tie is preserved).
- **Full PRP scrub on readback (ADR 0002).** On readback the note flows through the existing
  retriever (RBAC + PRP guard); a note tied to a PRP account is dropped at query time, and because
  ride-along prep derives its **whole** output (free text AND structured agreed_actions /
  observe_next AND the session_id) from the retriever-gated `surfaceable` set, the **entire** PRP
  record is scrubbed at every scope level — not just its body.
- **Records the DM's own observations — not autonomous action (FR-011).** The write stores the
  human's input verbatim (no generation/alteration); the system never acts on it.

**Step 10b — voice capture — task P10-T5 — DONE**
(`src/coach/llm/transcribe.py` + `src/coach/components/close_capture.py`; purely additive on
Step 10a):
- **Transcription seam** — a `Transcriber` interface with a lazy **`AmazonTranscribe`** (region +
  S3 bucket from config — `Settings.transcribe_s3_bucket`; boto3 imported on first real use, so
  importing/constructing needs no AWS creds; the real upload→job→poll→fetch path is `# pragma: no
  cover`) and a deterministic **`FakeTranscriber`** for tests — **no live AWS call** in CI. Mirrors
  the LLM / embeddings seams.
- **Claude structures only the DM's stated items — never invents.** `draft_close_record(_from_voice)`
  builds a draft `CloseRecord` where **`observations` are the DM's verbatim transcript — the LLM
  never alters them** (any LLM-supplied observations are ignored). The LLM only EXTRACTS the
  `agreed_actions` / `observe_next` the DM actually stated; the prompt forbids inventing, an
  unstated category → an empty list, and an unparseable / non-list response → empty lists (structure
  nothing rather than fabricate). The LLM stays behind the existing injectable client (model id from
  config; FakeLLM in tests); it decides nothing and takes no action.
- **The draft is reviewable before save.** The capture flow **returns a draft and never writes** —
  the DM reviews/edits, then **saving reuses the Step 10a single-door write path**
  (`save_close_record`), which re-enforces **writer-scope RBAC** (out-of-scope rejected like
  not-found) and **PRP fully scrubbed on readback** (body + structured fields + id). **No new write
  path.** An empty transcript is rejected (validation).
- **The loop closes via voice.** A voice-captured, DM-saved CLOSE record surfaces in the next
  ride-along prep via the same scoped + PRP-scrubbed read.

### Tests
- `tests/unit/test_data_access.py` (**T018**) — shape/counts, signal variety, determinism
  (same seed → identical data), synthetic-only provenance, store round-trip, plus the
  PRP and per-brand assertions.
- `tests/unit/test_schemas.py` (**T019**) — every recommendation requires a non-empty
  `reason`.
- `tests/unit/test_rbac.py` (**T017**) — each scope level sees exactly its territory;
  out-of-scope reads raise `ScopeError`; out-of-scope vs non-existent reps are
  indistinguishable (FR-014); role → scope mapping comes from config.
- `tests/unit/test_prp.py` (**T017A**) — no PRP HCP (or its metrics / call activity) is
  returned through any read at any scope level; deterministic for the seed; ≥1 PRP HCP
  exists.
- `tests/unit/test_ranking.py` (**T020, T022, T022a**) — score = Σ(normalized × weight);
  changing a weight changes a signal's influence predictably and a signal at its cap
  contributes exactly its weight (T020); every `RepRanking` has a structured reason with the
  four signal contributions + ≥1 top-contributor (T022, FR-003); perturbing a non-signal
  attribute (tenure, name) leaves ranks/scores/reasons unchanged (T022a, FR-017); plus the
  **anti-LLM-ranking guard** (narration changes only `reason.summary`).
- `tests/unit/test_ranking_golden.py` (**T021**) — seed-42 / District-1 golden: ranked
  order, scores, and reason structure (raw + normalized) match the committed fixture, keyed
  on Brand enum names (independent of the display spelling).
- `tests/component/test_coaching_focus.py` (**T026**) — example-based focus selection (seed
  42) and order; changing a config threshold shifts the selection predictably; every
  `CoachingFocus` has a structured reason with ≥1 data point (FR-010); the no-signal default
  and no-history cases (FR-018); plus the **anti-LLM guard** (narration changes only
  `reason.summary`).
- `tests/component/test_notes_retriever.py` (**T011**) — implements the `Retriever` Protocol;
  determinism (same query/seed → same notes; two seeded builds agree); **RBAC** (a DM cannot
  retrieve another district's notes → `ScopeError`; region across its region; `all`
  everywhere); **PRP** (≥1 PRP-tied note exists; never returned at any scope level; exclusion
  is selective); and **config/offline** embeddings (model id from config, raises if unset, no
  boto3 client/live Bedrock call).
- `tests/component/test_ride_along_prep.py` (**T029**) — deterministic seeded assembly
  (expected notes / agreed actions / observe-next; most-recent-N from config); **RBAC**
  (out-of-scope rep → `ScopeError`) and **PRP** (a PRP-tied note + its structured fields never
  surfaced); provenance on every item (FR-010); the **anti-LLM guard** (only summary + opening
  change); and the FR-018 edge cases (no-history `EmptyState`; missing field → "not recorded").
- `tests/component/test_accounts_context.py` (**T032**) — focused example-based selection
  (seed 42, capped, a subset of the book); **per-brand labeling** (one `AccountFocus` per
  (account, brand); LILETTA renders); **mismatch flag** (high-opp + low calls flagged with a
  reason; well-served not flagged; the config threshold flips it); **RBAC** (`ScopeError`) and
  **PRP** (PRP accounts never appear); explainability (FR-010); the **anti-LLM guard** (only
  `reason.summary` changes); FR-018 edges (no-accounts → empty; missing calls → "not recorded").
- `tests/component/test_opener.py` (**T035**) — deterministic talking-point selection (seed
  42, expected source/ref order) + config cap; provenance on every point mirrored in the
  reason (FR-010); suggestion-only data, no action (FR-011); the **anti-LLM guard** (only
  `text` + `reason.summary` change; no points added); FR-018 no-priority rep → positive
  default opener, not fabricated.
- `tests/e2e/test_brief_rubric.py` (**T038**) — end-to-end brief assembly: the **5-section
  checklist rubric** (SC-002, all five sections present + every recommendation has a visible
  reason); the **consistency check** (F4/SC-004 — two runs → identical `model_dump`); the
  **narrate-before-expose guard** raises (direct mutation + an empty-LLM end-to-end); **RBAC**
  (out-of-scope rep → `ScopeError`) + **PRP** (PRP accounts never in the brief); **FR-018** no-
  history rep → valid, rubric-passing brief; and suggestion-only (pure data, no action path).
- `tests/e2e/test_api.py` (**Step 5b — T016/T025/T037**, via FastAPI `TestClient`) — the
  **read-only surface** (only `GET` routes exist — replaces the superseded F6); **RBAC over the
  API** (DM → own district only, region → its region, `all` → everything — replaces the
  superseded F8); an out-of-scope `rep_id` → `403` **indistinguishable** from not-found
  (FR-014); the **caller cannot widen their own scope** via input; **PRP** accounts never appear
  in a brief at any scope; **no `PENDING_*` placeholder** in any response (and an un-narrated /
  empty-LLM path is a `500`, never leaked placeholder text); and the **per-request connection**
  (each request opens + closes its own store connection).
- `tests/e2e/test_audit.py` (**T040 / F3**) — one **privacy-safe audit record** per brief (and
  per reps list) carrying only allow-listed safe fields; HR-sensitive rep fields and private HCP
  fields (names, metrics, raw PII) **never appear in the request-path logs**; and
  `build_audit_record` **refuses** a HR-sensitive field by construction (FR-016).
- `tests/e2e/test_ui.py` (**T039**) — the page is **served as HTML** with the seeded-user
  selector; it is **read-only** (the whole app surface is GET-only, and the page issues no
  mutating fetch — it references only the GET endpoints); the rendered brief carries a
  **non-placeholder reason on every one of the five sections** (FR-010, via the offline fake-LLM
  path); and the **no-history rep** renders a clean empty-state message (FR-018).
- `tests/component/test_theme_aggregation.py` (**P7-T1/T2/T3**, 13 tests) — Phase 7: a
  deterministic **golden** (seed 42, region) for the themes/counts/order; **patterns-only**
  (structural — no rep-identity field — plus a serialized **substring** check that no rep id/name
  leaks); **same-source** (the aggregate equals an independent per-rep coaching-focus tally);
  **RBAC** (region/all allowed, a DM + a rep → `ScopeError`, and a **2-region** dataset proving
  region isolation + predictable count changes); **small-cell suppression** (a small district /
  rare theme is masked at the default threshold, and changing `aggregation_min_cell` changes what
  is suppressed predictably); the **anti-LLM guard** (counts unchanged, only `summary` written;
  no rep id in the LLM input); and **explainability** (counts on every theme).
- `tests/component/test_summit.py` (**P8-T1/T2**, 12 tests) — Phase 8: deterministic Summit
  scores + the **what-if lift** (lifts 2/1/0 on a 3-district set) and determinism; **per-team
  config-driven** (identical inputs + different configured formulas → different scores) and the
  formula scaling scores predictably; **rollup integration** (the Summit signal folds in via the
  normalized rollup — `total_score` = four-signal score + normalized contribution; a zero weight
  turns it off); **explainability** (lift + targets with raw numbers); the **anti-LLM
  guard**; **RBAC + PRP** (PRP rows scrubbed; a DM aggregates only their own district); and the
  **`recovery_fraction`** hardening (default 1.0 preserves prior behavior; a different value
  changes the lift predictably; two teams with different recovery → different results).
- `tests/component/test_covariant.py` (**P9-T1/T2/T3**, 9 tests) — Phase 9: a deterministic
  **golden** (seed 42, DM D1 — rows/overall/per-variable rates+lift/optimal blend); determinism;
  **config-driven success measure** (relaxing it changes the result predictably; `meets_success_measure`
  gates verified); **explainability** (the reason carries the variables, the success measure, and
  the numbers + the honesty note); **insufficient-data honesty** (a thin slice → a clear state, no
  association); **RBAC + PRP** (PRP rows scrubbed; a DM aggregates only their district, "all" reads
  more); and the **anti-LLM guard**.
- `tests/e2e/test_close_record.py` (**P10-T1…P10-T4 / Step 10a**, 8 tests) — Phase 10: the write
  stamps the author from context; **writer-scope RBAC** (out-of-scope + not-found → `ScopeError`,
  indistinguishable); region/all writers within scope; **the loop closes** (a saved record surfaces
  in the next ride-along prep via the normal readback); **full PRP scrub on readback** — a PRP-tied
  close note's **free text AND structured fields (agreed_actions, observe_next) AND its session_id**
  never surface at any scope (ADR 0002); **collision-free ids** (two records → distinct rows, no
  cross-contamination); validation rejects a malformed record; and the write **records the DM's
  input verbatim** (no autonomous action).
- `tests/e2e/test_close_capture.py` (**P10-T5 / Step 10b**, 11 tests) — Phase 10 voice: the
  **deterministic offline `FakeTranscriber`** (no live AWS) + `AmazonTranscribe` constructs without
  creds (lazy); **structuring fidelity / no fabrication** (observations stay verbatim, the LLM can't
  alter them; unstated → empty; unparseable → empty; empty transcript rejected); **review before
  save** (the draft is not persisted; the DM's edit is what saves); **writer-scope RBAC on save**
  (out-of-scope rejected like not-found); **the loop closes via voice**; and **PRP fully scrubbed**
  on the voice path (body + structured fields + id, every scope).
- Reviewed by the **constitution-guardian** subagent — Phases 1, 2, 3, **all four Phase 4
  brief-section components**, **the Phase 5 orchestrator + assembly**, **the Step 5b read-only
  API**, **the Phase 6 web UI**, **the Phase 7 theme aggregation**, **the Phase 8 Summit
  optimization**, **the Phase 9 covariant analysis**, **and the Phase 10 CLOSE capture (Step 10a
  write path + Step 10b voice)** all **COMPLIANT** (Phase 9: config-driven labeled success measure,
  transparent deterministic association in code — not a black-box model, not LLM-decided — thin
  data handled honestly, reads only through the data-access layer, anti-LLM guard. Phase 10: write
  through the single door with writer-scope RBAC, out-of-scope rejected like not-found, the WHOLE
  record — free text + structured fields + id — PRP-scrubbed on readback, collision-free ids,
  records the DM's input verbatim — no autonomous action. Step 10b voice: Transcribe behind an
  interface with a fake in tests (no live AWS); Claude structures only the DM's stated items and
  never invents (observations verbatim); the draft is reviewable; saving reuses the same 10a door —
  no new write path.
  Phase 7: patterns/counts-only enforced structurally + small-cell suppression; RBAC region/all
  with DM rejected; themes from the shared signals — no drift; aggregation in code, LLM
  wording-only; reads only through the data-access layer. Phase 8: per-team Summit formula
  config-driven + labeled placeholder, no hard-coded numbers; the what-if lift computed
  deterministically in code, not LLM-decided; integrated via the normalized rollup so weights stay
  meaningful, enabled by default (weight 0.2, tunable; 0 turns it off); `recovery_fraction` a tunable per-team config with default 1.0
  preserving prior behavior; reads only through the data-access layer (RBAC + PRP); anti-LLM guard
  present) — (Principle V scope levels + scope-from-config,
  caller cannot choose scope; Principle IV PRP scrubbing — reused helpers, not a bypass, unaffected
  by the per-thread connection change; Principle I/VI/VIII deterministic + fixed DAG (no agentic
  loop) + GET-only/no-mutation (API and UI) + LLM-out-of-deciding + no browser-side ranking +
  config-controlled; Principle II provenance/explainable + reason shown under every UI
  recommendation + narrate-before-expose enforced through the API; FR-014 403 indistinguishable
  (API and UI); FR-016 allow-list logging; Principle III synthetic-only; Principle VII behind
  interfaces + per-request connection); no golden-rule violations. Recorded watch items
  (not violations): narrow the global `KeyError`→403 to a dedicated `RepNotFoundError` so genuine
  bugs aren't masked; consider auditing denied/`403` access; keep `get_user.name` out of any
  response/log; the UI's seed-picker role labels (RD/Head of Sales) are cosmetic demo text to
  reconcile when the RD/RBE role names are confirmed; tune the ADR 0001 normalization caps with
  the business. **Phase 8 (Summit):** soften the stale `SummitTarget.projected_share_trend`
  schema comment (only "→ 0.0" at the default recovery), and add a `[0.0, 1.0]` bounds
  check/validator on `SummitFormula.recovery_fraction` so an out-of-range per-team config can't
  produce a nonsensical (dishonest) reason — both low-priority, non-blocking.

### Spec Kit workflow (completed steps)
constitution → specify → clarify → plan → tasks → analyze. The feature spec lives in
`specs/001-morning-coaching-brief/` (`spec.md`, `plan.md`, `data-model.md`, `tasks.md`,
`research.md`, `quickstart.md`, `contracts/`, `checklists/`).

### Claude Code setup
- `CLAUDE.md` — project instructions and golden rules.
- **3 subagents** (`.claude/agents/`): `data-explorer`, `test-runner`,
  `constitution-guardian`.
- **2 project skills** (`.claude/skills/`): `gen-synthetic-data`, `run-checklist-eval`
  (the other skills are Spec Kit tooling).
- **2 hook mechanisms**: a **PostToolUse format hook** (`.claude/settings.json` →
  `scripts/claude-format-hook.sh`, runs ruff after edits) and the **Spec Kit lifecycle
  hooks** (`.specify/extensions.yml`: git auto-commit + agent-context update around each
  speckit step).

---

## 3. Decisions log — DECIDED

- **MVP = the morning coaching brief** (capabilities 1–4: who to ride with + why; what to
  coach; what happened last time; accounts/HCPs + business context; plus the opener). The
  capabilities that were originally *out of scope for the MVP* are now **built post-MVP**:
  Summit ranking optimization (**Phase 8 — DONE**) and aggregating coaching themes for leadership
  (**Phase 7 — DONE** — a **scoped, aggregate-only** view: patterns and counts only, never named
  individuals; region/all scope only).
- **Clarify answers** (Session 2026-06-07):
  - Ranking uses the **four named signals** — declining share, low call activity in key
    accounts, missed coaching follow-up, business opportunity/risk — with **transparent,
    visible weights**.
  - The preparedness measure is a **fixed 5-section checklist rubric** (one per brief
    section), enforced by automated tests.
  - Data scale = **one small realistic region, 2 districts** (8–12 reps/district,
    15–30 accounts-HCPs/rep, 2–3 coaching sessions for most reps).
- **Ranking is deterministic (code), never decided by the LLM** — the LLM only narrates
  the structured reason into clear language (tasks **T023** code vs **T024** narration).
- **Per-brand metrics decision (I1)** — share, volume, spend, and call activity are
  attributable to an `(account, brand)` pair; one account can carry multiple brands.
- **PRP rule (FR-020)** — HCPs flagged `prp` must be **scrubbed at the data-access layer**
  before any result reaches a field user (refines the privacy requirement FR-016).
- **Notes retriever enforces RBAC + PRP at query time (ADR 0002)** — the vector-search path
  is part of the single door, not a separate trust boundary: it re-applies the same RBAC scope
  and PRP scrubbing on every query, reusing the existing helpers. See
  [`docs/adr/0002-notes-retriever-rbac-prp.md`](adr/0002-notes-retriever-rbac-prp.md).
- **Fixed-graph orchestration; narrate before expose (ADR 0003)** — the brief is composed by a
  fixed LangGraph DAG (deterministic order, no agentic loop; `AccessContext` threaded through
  every node) and an assembly guard that **rejects any brief containing an un-narrated
  placeholder**. See
  [`docs/adr/0003-orchestration-and-narrate-before-expose.md`](adr/0003-orchestration-and-narrate-before-expose.md).
- **Brand portfolio modeled** — LUPRON PEDS, LUPRON URO, LUPRON GYN, Synthroid, and
  **LILETTA** (brand spelling **finalized**; `Brand` enum member `liletta` = "LILETTA").
- **Terminology** — **AEBAT** is a tool/website that shows strategic spend and
  speaker-program spend by rep (it is **not** a team). **APEX** is the internal analytics
  support team (a support team / secondary user, **not** a data source).
- **Role & access model (scope levels)** — access is scoped by **level**, not by job
  title. The code scopes by level; the role-name → level mapping comes from a single
  config/enum source. All **non-rep** roles have **full access (no read-only)**:
  - **Rep → self only** (limited; role modeled, **no MVP workflow**).
  - **DM → own district** (full within the district).
  - **RD → whole region** (full).
  - **RBE → whole region** (full + action rights).
  - **Head of Sales → all regions** (full).

  The MVP's first workflow remains the **DM opening the brief + the coaching close**; the
  other roles get **access rules only — no dedicated screens** in the MVP.

---

## 4. Stakeholder answers — recorded as project facts

- **Access** — a DM sees **only their own district**. Account overlaps between DMs happen
  but are rare exceptions and are **out of scope for the MVP**.
- **Region-level role has FULL access** — it can take actions (e.g., add notes, flag a
  rep). It is **NOT read-only**. *(Now captured as the decided scope-level model in §3;
  this supersedes the earlier "read-only" wording.)*
- **Hierarchy** — Rep → DM → **RD (Regional Director)** → Head of Sales. There is also an
  **"RBE"** who reports **directly to the Head of Sales**, has full access, and supports
  the Head of Sales and the DMs. **DMs do NOT report to the RBE.**
- **Scope refinement — two coaching moments**:
  - **OPEN** — the morning brief: where are we going, what is the focus, what are the
    goals. *(The MVP currently builds the OPEN.)*
  - **CLOSE** — end of the coaching session: observations and areas of focus/development
    going forward. *(Planned new capability, to be specified later.)*
- **Veeva coaching notes** — a mix of structured fields and free text; a **de-identified
  example will be shared**.
- **IQVIA / PRP** — the only rule is that **PRP physicians are scrubbed out** before any
  report reaches the field.
- **Summit** — calculation logic is documented and shareable, but **differs per team**
  (depends on each team's IC plan), so build it **configurable per team** when we reach
  that phase.
- **"Good coaching" framework** — none exists formally; it is best practice from the
  strongest DMs. The business suggested a **~60-minute workshop** with a few DMs and RDs.

---

## 5. Open items — OPEN (pending)

> **All six capabilities are built (§6); nothing below is a missing capability.** What remains is
> **assumptions to confirm with the business**, **productionization** (real data connectors, auth,
> a polished + leadership UI), and optional hardening — follow-up work, not gaps.

- **Confirm "RBE" expansion (terminology only).** Working definition: a **regional
  business support role reporting to the Head of Sales**, with region scope + action
  rights. *Does NOT block Phase 2* — role names are config; the scope level is decided (§3).
- **Confirm "RD" = the role earlier mislabeled "RBD" (terminology only).** *Does NOT block
  Phase 2* for the same reason — only the label is open, not the region/full-access level.
- **Tune scoring/selection parameters with the business.** The **coaching-focus
  trigger thresholds** (`Settings.focus_thresholds`, default 0.5 / 1 / 1 / 1) and the
  **ranking normalization caps** (`Settings.ranking_norm_caps`, default 3.0 / 10 / 3 / 10 —
  ADR 0001) are config-visible product judgments. Review/tune them once the business sees real
  output. When changed, the T021 golden and the coaching-focus example fixture must be
  regenerated together (they move in lockstep).
- **Labeled assumptions to confirm with the business (Phases 8–9).** All config-only, no engine
  change to swap:
  - **Phase 8 — the Summit per-team formula is a PLACEHOLDER** (`Settings.summit_formulas` /
    `SummitFormula` coefficients). Representative only — the business will supply each team's real
    Summit / IC-plan logic; the engine never hard-codes a team's numbers.
  - **Phase 8 — the Summit `recovery_fraction` is an ASSUMPTION to tune** (default **1.0** = full
    recovery; per-team config, env `COACH_SUMMIT_RECOVERY_FRACTION`). A full recovery may be
    optimistic — confirm/tune the per-team value with the business.
  - **Phase 9 — the covariant "success" measure is an ASSUMPTION to confirm.** Phase 9 ships with
    a clearly-labeled config DEFAULT (`SuccessMeasure`: rising share + on/above target); confirm /
    tune the real definition with the business (the analysis is computed against it).
- **F6 / F8 superseded → now SATISFIED for the read-only MVP API (Step 5b).** The old
  read-only / read-only-RBD guard tests were recorded as **SUPERSEDED** (region-level roles now
  have full write/action access). For the current **entirely read-only** API they are now met
  directly: **F6** by the read-only-surface test (only `GET` routes exist —
  `test_only_get_routes_are_exposed`) and **F8** by the **RBAC route-authorization tests**
  (`district`/`region`/`all` each see exactly their scope; out-of-scope → `403`; the caller
  cannot widen scope). Extend with **per-route / scope-level write-authorization tests when
  write/action routes are designed** (region roles act, not read-only).
- **Narrate before exposing a ranking — CLOSED (enforced in assembly AND through the API).** The
  deterministic builders leave `reason.summary` as a `PENDING_SUMMARY` placeholder until the
  `narrate_*` step runs. The orchestrator narrates every section inside the graph and
  `assembly.assert_narrated` **RAISES** on any surviving placeholder (Step 5a, T038); the **API
  re-checks at the boundary** (`assert_narrated` on the brief, ranking-summary check on
  `/api/reps`), so no response body can contain `PENDING_SUMMARY` / `PENDING_TEXT` /
  `PENDING_OPENING` — an un-narrated path becomes a clean `500` (tested in `test_api.py`). Both
  halves are now done. (Originally from the Phase 3 guardian review; closed by ADR 0003 + Step 5b.)
- **Per-request DB connection at the data-access boundary — DONE (Step 5b).** The API opens a
  **fresh store (its own connection) per request** via a FastAPI dependency and closes it when
  the request ends; the store internally uses a **small per-thread connection pool** so the
  orchestrator's parallel section reads each get their own connection. This replaced the single
  process-wide `check_same_thread=False` connection and also fixed a latent concurrency race that
  connection had under the parallel nodes. RBAC + PRP still run on every read regardless of
  connection. Maps to a **connection pool / Aurora** in production. (Closed the Step 5a guardian
  watch item.)
- **Optional RBAC hardening (deferred, non-blocking)** — from the Phase 2 guardian review:
  (#3) `rbac.scoped_rep_ids` / `rep_in_scope` "fail closed to empty/`False`" on an unmapped
  scope level instead of raising loudly — currently **unreachable** (every `Role` is mapped;
  `scope_level_for` raises `KeyError` if not); (#4) `AccessContext` doesn't assert
  `self` → `rep_id` set / `district` → `district_id` set — already **fails closed** safely.
  Both are fail-closed today and satisfy FR-014; optional to tighten before real connectors.
- **Doc-sync — DONE.** The scope-level / full-access model is now reflected across all
  docs: `README.md`, `CLAUDE.md`, `docs/`, the constitution (Principle V + preamble), and
  the full spec-kit set (`spec.md` FR-013, `plan.md` Constitution Check row V,
  `data-model.md`, `tasks.md` T008/T017/F6/F8, `research.md`, `quickstart.md`,
  `contracts/data-access.md`, `contracts/api.md`). No region "read-only" wording remains
  except the intentional F6/F8 SUPERSEDED history.
- **CLOSE capture — BUILT (Phase 10).** The text write path + voice capture are done; any future
  refinement of the CLOSE structure is informed by the coaching workshop below.
- **Schedule the coaching workshop** (~60 min, a few DMs + RDs) — it will refine the
  coaching-focus logic and the CLOSE structure.
- **Receive the de-identified Veeva coaching-note example** — needed to design the
  ride-along-prep RAG over real-shaped notes.
- **Performance / latency test (SC-001)** is **deferred for the MVP** (no perf test task
  in scope; recorded in `tasks.md` as deferred check "C2").
- **A few originally-scoped foundational tasks are still unchecked in `tasks.md` (none is a
  capability).** **T013** — the PII guardrail seam — ships today as a placeholder package
  (`src/coach/guardrails/__init__.py`); its pass-through `pii.py` and the Bedrock Guardrails
  wiring are future work (see *Productionization* below). **T041** (a dedicated
  `tests/e2e/test_synthetic_only.py`) and **T042** (a named `tests/e2e/test_quickstart.py` for
  quickstart scenarios A–D) are not yet written as standalone files — their behaviour is
  already exercised, though: the synthetic-only rule by the commit-time hook plus
  `GenerationMeta(synthetic=true)`, and the quickstart scenarios by the existing RBAC, rubric,
  and determinism-golden e2e tests. Separately, **T007A** and **T012** are **built** (the
  `Brand` enum and the `BedrockLLM` wrapper both exist in the repo) but their checkboxes in
  `tasks.md` are stale and should be ticked.
- **Productionization (future work, beyond the six capabilities).** None changes a capability;
  each swaps a synthetic/MVP piece for a managed one behind the existing interfaces:
  - **Real data-source connectors** — Veeva / IQVIA / Summit / Aurora / Athena / Bedrock
    Knowledge Bases behind the same `DataAccess` / `Retriever` seam (the single door, RBAC + PRP
    unchanged); replaces the synthetic generator.
  - **Real authentication** — Amazon Cognito → `AccessContext` (the API already resolves identity →
    role → scope from config; swap the `X-User-Id` stub for real authn).
  - **UI polish + hardening** — the served `/` page already surfaces the brief (with Summit as a
    5th contributor and the covariant insight in the Accounts & business section), the role-gated
    leadership themes view, and the Record-close panel (backed by `GET /api/themes` and
    `POST /api/brief/{rep_id}/close`); productionization is richer rendering + hardening, not a new
    screen.
  - **Optional hardening from the reviews** — CLOSE `save` audit semantics (the `INSERT OR REPLACE`
    overwrite-by-id), a mocked integration test for the real `AmazonTranscribe` path, and a
    layer-level PRP filter on `get_coaching_sessions` (today PRP on the structured fields is
    enforced by the ride-along `surfaceable` intersection — ADR 0002).

---

## 6. Phase roadmap

| Phase | Scope | Status |
|-------|-------|--------|
| **Phase 1** | Foundation: interface, schemas, store, config, seeded generator + the PRP/per-brand **amendment** | **DONE** |
| **Phase 2** | **RBAC** (T008, scope levels: self/district/region/all) + **PRP scrubbing enforcement** (T008A) at the data-access layer; tests T017/T017A | **DONE** |
| **Phase 3** | **Deterministic ranking** (T023, incl. signal normalization so config weights control influence) + LLM reason narration (T024); tests T020/T021/T022/T022a | **DONE** |
| **Phase 4** | The **five brief sections**: (1) coaching focus ✅ T026/T027; (2) ride-along prep ✅ (T010/T011 + T029/T030); (3) accounts + per-brand context ✅ T032/T033; (4) opener ✅ T035/T036 | **DONE** (all five sections) |
| **Phase 5** | **Assembly + rubric + API.** **Step 5a** ✅ — the fixed-DAG **orchestrator + brief assembly + 5-section checklist rubric** (T015, T028, T031, T034, T038; ADR 0003). **Step 5b** ✅ — the **read-only FastAPI API** (T014, T016, T025, T037, T040): GET-only, identity→scope-from-config, per-request connection, FR-014 403, PRP-safe, privacy-safe logging | **DONE** (both steps) |
| **Phase 6** | **UI** (T039) — minimal read-only web page rendering the 5 sections + each reason; seeded-user selector (API enforces scope); per-brand accounts + mismatch; clean 403/empty states; offline demo server | **DONE** |
| **Phase 7** | **Theme aggregation** (capability #6) — leadership view of themes across reps: **patterns/counts only, never named individuals** (structural + small-cell suppression), **RBAC-scoped** (region/all only; DM rejected), deterministic from the shared signals, LLM wording-only (P7-T1/T2/T3) | **DONE** (role-gated leadership themes view on `/`, backed by `GET /api/themes`) |
| **Phase 8** | **Summit optimization** (capability #5) — Summit / IC-plan lift as a new ranking signal **computed in code** (deterministic; per-team **config placeholder** formula + tunable `recovery_fraction`); folded into the normalized rollup, **enabled by default** (weight 0.2, tunable via `COACH_WEIGHT_SUMMIT`; 0 turns it off); the LLM never scores it (P8-T1/T2) | **DONE** (5th `summit_opportunity` contributor in every brief's Priority reason on `/`) |
| **Phase 9** | **Covariant analysis** (capability #4) — deeper accounts insight **computed in code** (transparent counts/rates/lift, not a black-box model, not LLM-decided); **config-driven** success measure (labeled assumption); thin data handled honestly; reads through the single door (P9-T1/T2/T3) | **DONE** (covariant insight in the Accounts & business section on `/`) |
| **Phase 10** | **Verbal feedback / CLOSE capture** (capability #2). **Step 10a** ✅ — the text **CLOSE write path** (P10-T1…T4): first WRITE through the single door, writer-scope RBAC (out-of-scope rejected like not-found), the loop closes into the next ride-along prep, **full PRP scrub on readback** (structured fields + free text; ADR 0002), collision-free ids, records the DM's input verbatim. **Step 10b** ✅ — **voice capture** (P10-T5): `Transcriber` seam (lazy Amazon Transcribe + fake, no live AWS); Claude structures only the DM's stated items (observations verbatim, never invents); reviewable draft; saving reuses the 10a door | **DONE** (both steps) |

> ✅ **ROADMAP COMPLETE — Phases 1–10 DONE. ALL SIX original capabilities are built end to end.**
> The morning coaching brief runs end to end (**synthetic data → RBAC/PRP data-access layer →
> deterministic ranking → the five brief sections → the orchestrated, narrated, validated brief →
> the read-only API → the read-only web UI**), plus the four post-MVP capabilities: **#6 theme
> aggregation (Phase 7), #5 Summit optimization (Phase 8), #4 covariant analysis (Phase 9), and #2
> verbal feedback / CLOSE capture (Phase 10 — text write path + voice)**. `pytest` → **215
> passed**. What remains is **productionization** (real data connectors, auth, UI polish/hardening)
> and confirming the labeled assumptions with the business — **not new
> capabilities** (§5, §7).

### Diagrams

Four diagrams live in [`docs/diagrams/`](diagrams/), referenced as **images** in `README.md`
and `docs/technical-architecture.md` (GitHub renders an SVG referenced as an image file, not
inline `<svg>` code):

- **`architecture.svg`** — the **complete target architecture** (the whole system, every capability).
- **`flow-detailed.svg`** — the detailed **OPEN→CLOSE flow**, with the two safety gates (rep-in-scope, and narrate-before-expose).
- **`ranking-rollup.svg`** — how **rep ranking** rolls the per-(account, brand) signals up into one score per rep.
- **`sequence.svg`** — a **swimlane** of who calls whom to build and close a brief (solid = request, dashed = response).

---

## 7. How to resume

1. **Read this file first** (`docs/project-status.md`) for current state and decisions.
2. Then read **`specs/001-morning-coaching-brief/`** — `spec.md`, `plan.md`,
   `data-model.md`, `tasks.md` — for the detailed requirements and task IDs.
3. Then read **`CLAUDE.md`** for the golden rules and stack/commands.
4. Skim **`src/coach/`** for the built foundation + RBAC/PRP + ranking + the five brief-section
   components (coaching-focus, notes-retriever, ride-along-prep, accounts-context, opener) +
   the **orchestrator + assembly** (`src/coach/orchestrator/`) + the **read-only API**
   (`src/coach/api/app.py`), **audit/logging** (`src/coach/observability/audit.py`), the
   **web UI** (`web/index.html`), the **offline demo server** (`src/coach/api/demo.py`), the
   **Phase 7 theme aggregation** (`theme_aggregation.py`), **Phase 8 Summit** (`summit.py`),
   **Phase 9 covariant** (`covariant.py`), and **Phase 10 CLOSE capture** — the write path
   (`DataAccess.save_close_record` + `CloseRecord`) and voice (`llm/transcribe.py` +
   `components/close_capture.py`),
   and run `uv run pytest -q` to confirm the suite is green (**215 passing**).

**Run it locally:**
- **Offline demo (no AWS, recommended for a walkthrough):** `uv run uvicorn coach.api.demo:app
  --reload`, then open `http://127.0.0.1:8000/`. The demo server auto-seeds synthetic data and
  uses an offline narrator + fake embeddings — no live Bedrock call. Switch the seeded user
  (dm_d1 / dm_d2 / region_r1 / hos_1) to see RBAC scope change; open a rep for the full brief.
- **Production wiring:** `uv run uvicorn coach.api.app:app --reload` with `BEDROCK_MODEL_ID` /
  `AWS_REGION` / `BEDROCK_EMBED_MODEL_ID` set and a seeded DB
  (`uv run python -m coach.synthetic.generate`).

**What's next (the roadmap is COMPLETE — all six capabilities built; no new capability is
pending). The remaining work is productionization + confirming assumptions (§5):**
1. **Confirm the labeled assumptions with the business** (config-only, no code change): the
   **Summit** per-team placeholder formula + `recovery_fraction`, the **covariant** `SuccessMeasure`,
   and the **RD/RBE** role names. Use the coaching workshop + first real-shaped data to tune them.
2. **Productionize behind the existing interfaces** (none is a new capability): **real data-source
   connectors** (Veeva / IQVIA / Summit / Aurora / Athena / Bedrock Knowledge Bases behind the same
   `DataAccess` / `Retriever` door — RBAC + PRP unchanged), **real auth** (Cognito → `AccessContext`),
   and **UI polish + hardening** (the served `/` page already surfaces the Phase 7 themes via the
   role-gated leadership view + `GET /api/themes`, the Phase 8 Summit insight as a 5th brief
   contributor, the Phase 9 covariant analysis in the Accounts & business section, and the Record-
   close panel via `POST /api/brief/{rep_id}/close`). Plus the optional review hardening (CLOSE `save` audit semantics; a mocked
   `AmazonTranscribe` integration test; a layer-level PRP filter on `get_coaching_sessions`).
3. **Prepare the demo for the business** — run the offline demo (above), walk the brief + the
   visible reasons (and the voice CLOSE loop), and gather feedback to drive #1.

**Reminders to carry forward:**
- **Narrate before expose — done and enforced.** `assert_narrated` raises on any surviving
  `PENDING_*` placeholder in assembly (ADR 0003, T038) and the API re-checks at the boundary
  (T016/T025/T037). The **UI must not bypass it** — render only what the API returns.
- **Tune the config-visible values with the business.** The **ranking normalization caps**
  (ADR 0001), the **coaching-focus thresholds**, and the **account selection / mismatch rule**
  are all config-visible product judgments — review/tune them once real output is visible.

(The brand spelling is confirmed — **LILETTA**; the golden/fixtures key on Brand enum names so
they were unaffected.)
