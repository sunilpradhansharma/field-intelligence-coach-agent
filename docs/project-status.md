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

**Phase 1 Foundation (incl. the PRP + per-brand amendment) and Phase 2 (RBAC + PRP
enforcement) are COMPLETE and tested.** `pytest` → **35 passed**.

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
- Reviewed by the **constitution-guardian** subagent — Phase 1 and Phase 2 both
  **COMPLIANT** (Principle V scope levels + Principle IV PRP scrubbing verified on every
  read path); no golden-rule violations.

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
- **Brand portfolio modeled** — LUPRON PEDS, LUPRON URO, LUPRON GYN, Synthroid, Litella
  (the **"Litella" spelling is unconfirmed**).
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

## 4. Stakeholder answers (Nisha) — recorded as project facts

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
  strongest DMs. Nisha suggested a **~60-minute workshop** with a few DMs and RDs.

---

## 5. Open items — OPEN (pending)

- **Confirm "RBE" expansion (terminology only).** Working definition: a **regional
  business support role reporting to the Head of Sales**, with region scope + action
  rights. *Does NOT block Phase 2* — role names are config; the scope level is decided (§3).
- **Confirm "RD" = the role earlier mislabeled "RBD" (terminology only).** *Does NOT block
  Phase 2* for the same reason — only the label is open, not the region/full-access level.
- **Confirm the "Litella" brand spelling** before the `Brand` enum value and the **T021**
  golden fixture are frozen. *Blocks:* freezing the enum and any committed golden data.
- **F6 / F8 superseded** — because region-level roles now have full **write/action**
  access, the old read-only API guard tests are recorded as **SUPERSEDED** in `tasks.md`
  (replace with per-route / scope-level authorization tests when write routes are designed).
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
| **Phase 2** | **RBAC** (T008, scope levels: self/district/region/all) + **PRP scrubbing enforcement** (T008A) at the data-access layer; tests T017/T017A | **DONE** (35 tests pass) |
| **Phase 3** | **Deterministic ranking** (T023) + LLM reason narration (T024) | **PLANNED (next)** |
| **Phase 4** | The **5 brief sections** (prioritization, coaching focus, ride-along prep, accounts/context, opener) | Planned |
| **Phase 5** | **Assembly + rubric + API** (orchestrator, 5-section checklist rubric test, FastAPI endpoints) | Planned |
| **Phase 6** | **UI** (minimal web page rendering the 5 sections + each reason) | Planned |
| **(New)** | **CLOSE capture** capability — observations + focus/development at session end | Planned additional capability (needs its own spec) |

---

## 7. How to resume

1. **Read this file first** (`docs/project-status.md`) for current state and decisions.
2. Then read **`specs/001-morning-coaching-brief/`** — `spec.md`, `plan.md`,
   `data-model.md`, `tasks.md` — for the detailed requirements and task IDs.
3. Then read **`CLAUDE.md`** for the golden rules and stack/commands.
4. Skim **`src/coach/`** for the built foundation + RBAC/PRP code, and run
   `uv run pytest -q` to confirm the suite is green (**35 passing**).

**Immediate next action:** build **Phase 3 (deterministic ranking)** — task **T023** (pure
code, fixed visible weights over the four signals; per-(account, brand) rollup to a single
per-rep value) and **T024** (LLM narrates the structured `reason` only — never decides
ranks/scores), with tests T020/T021/T022/T022a.

**Before freezing Phase 3 fixtures:** confirm the **"Litella" brand spelling** and author
the **T021 golden fixture** against the amended (PRP + 5-brand) seed — changing the brand
spelling afterward would invalidate the committed `Brand` enum value and the golden data.
