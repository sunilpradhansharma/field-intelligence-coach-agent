# Project Status — Field Intelligence Coach Agent

> **Living memory.** This file lets any person — or any new AI session — resume with
> full context. Sections are split into **BUILT** (in the repo now), **DECIDED**
> (confirmed by the stakeholder), and **OPEN** (still pending). Keep it current.
>
> Last updated: 2026-06-10.

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

**Phase 1 Foundation (incl. the PRP + per-brand amendment), Phase 2 (RBAC + PRP
enforcement), Phase 3 (deterministic ranking), and Phase 4 (all five brief sections —
ranking, coaching focus, ride-along prep, accounts/business context, opener) are COMPLETE
and tested.** `pytest` → **89 passed**. Next: Phase 5 (assembly + 5-section rubric + API).

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

### Phase 4 (IN PROGRESS) — brief sections, built one at a time
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
- Reviewed by the **constitution-guardian** subagent — Phases 1, 2, 3, and **all four Phase 4
  brief-section components** (**coaching focus**, the **notes retriever seam** +
  **ride-along-prep component**, the **accounts/business-context component**, and the
  **opener**) all **COMPLIANT** (Principle V scope levels; Principle IV PRP scrubbing — reused
  helpers, not a bypass; Principles I/VI deterministic + LLM-out-of-deciding + config-controlled
  + LLM adds no facts; Principle II provenance/explainable; Principle III synthetic-only;
  Principle VII behind interfaces); no golden-rule violations.

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
  coach; what happened last time; accounts/HCPs + business context; plus the opener).
  **Out of scope for the MVP:** Summit ranking optimization and aggregating coaching
  themes for leadership.
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
- **F6 / F8 superseded** — because region-level roles now have full **write/action**
  access, the old read-only API guard tests are recorded as **SUPERSEDED** in `tasks.md`
  (replace with per-route / scope-level authorization tests when write routes are designed).
- **Phase 5 requirement — narrate before exposing a ranking.** The deterministic scorer
  leaves `reason.summary` as the `PENDING_SUMMARY` placeholder until LLM narration (T024)
  runs. The **API / orchestrator MUST always run narration before any ranking reaches a
  user** — no un-narrated ranking (placeholder summary) should ever be surfaced. Add a test
  when the API lands asserting no response contains `PENDING_SUMMARY`. (From the Phase 3
  guardian review; not a Phase 3 bug — the scorer correctly leaves prose to T024.)
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
- **Spec the CLOSE capture capability** — a new spec, later (separate from the OPEN MVP).
- **Schedule the coaching workshop** (~60 min, a few DMs + RDs) — it will inform the
  coaching-focus logic and the CLOSE structure.
- **Receive the de-identified Veeva coaching-note example** — needed to design the
  ride-along-prep RAG over real-shaped notes.
- **Performance / latency test (SC-001)** is **deferred for the MVP** (no perf test task
  in scope; recorded in `tasks.md` as deferred check "C2").

---

## 6. Phase roadmap

| Phase | Scope | Status |
|-------|-------|--------|
| **Phase 1** | Foundation: interface, schemas, store, config, seeded generator + the PRP/per-brand **amendment** | **DONE** |
| **Phase 2** | **RBAC** (T008, scope levels: self/district/region/all) + **PRP scrubbing enforcement** (T008A) at the data-access layer; tests T017/T017A | **DONE** |
| **Phase 3** | **Deterministic ranking** (T023, incl. signal normalization so config weights control influence) + LLM reason narration (T024); tests T020/T021/T022/T022a | **DONE** |
| **Phase 4** | The **five brief sections**: (1) coaching focus ✅ T026/T027; (2) ride-along prep ✅ (T010/T011 + T029/T030); (3) accounts + per-brand context ✅ T032/T033; (4) opener ✅ T035/T036 | **DONE** (all sections; 89 tests pass) |
| **Phase 5** | **Assembly + rubric + API** (orchestrator/brief, 5-section checklist rubric test, FastAPI endpoints) | **NEXT** |
| **Phase 6** | **UI** (minimal web page rendering the 5 sections + each reason) | Planned |
| **(New)** | **CLOSE capture** capability — observations + focus/development at session end | Planned additional capability (needs its own spec) |

---

## 7. How to resume

1. **Read this file first** (`docs/project-status.md`) for current state and decisions.
2. Then read **`specs/001-morning-coaching-brief/`** — `spec.md`, `plan.md`,
   `data-model.md`, `tasks.md` — for the detailed requirements and task IDs.
3. Then read **`CLAUDE.md`** for the golden rules and stack/commands.
4. Skim **`src/coach/`** for the built foundation + RBAC/PRP + ranking + the five brief-section
   components (coaching-focus, notes-retriever, ride-along-prep, accounts-context, opener),
   and run `uv run pytest -q` to confirm the suite is green (**89 passing**).

**Immediate next action:** build **Phase 5 — assembly + rubric + API** (orchestrator/brief
assembly that wires the five built sections, the **5-section checklist rubric** e2e test, and
the FastAPI endpoints). All section components are done; Phase 5 composes them into the full
brief and exposes it.

**Two reminders to carry into Phase 5:**
- **Narrate before expose.** The orchestrator/API MUST run LLM narration on every section
  output **before** anything reaches a user — **no `PENDING_SUMMARY` (or `PENDING_TEXT` /
  `PENDING_OPENING`) placeholder should ever be surfaced**. Add a test asserting no response
  contains a pending placeholder once the API lands.
- **Tune the config-visible values with the business.** The **ranking normalization caps**
  (ADR 0001), the **coaching-focus thresholds**, and the **account selection / mismatch rule**
  are all config-visible product judgments — review/tune them once real output is visible.

(The brand spelling is confirmed — **LILETTA**; the golden/fixtures key on Brand enum names so
they were unaffected.)
