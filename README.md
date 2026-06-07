# Field Intelligence Coach Agent

An AI assistant that helps **district managers (DMs)** prepare for coaching their sales
representatives and make **fairer** decisions about where to spend limited field time.
Today, coaching preparation is inconsistent — it depends on which manager you get and how
much time they had that morning — and field time tends to be split *equally* rather than
*fairly* (where it is most needed). This project moves the team from "equal to fair" by
producing one clear **morning coaching brief**: who to ride with and why, what to coach,
what happened last time, which accounts matter, and how to open the conversation — with
**every suggestion showing its reason and the data behind it**. The assistant only
*suggests*; the manager always *decides*.

---

## MVP scope

> **This is a proof of concept (POC), built spec-first, using synthetic data only.**
> Today, only **Phase 1 (foundation) is built and tested** — see [Phases](#phases) below.

### In scope (MVP)

- The **morning coaching brief** and its **five sections**:
  1. **Rep + reason** — a ranked list of reps who need attention, each with its reason.
  2. **Coaching focus** — 1–3 focus areas for the chosen rep, each with its reason.
  3. **Ride-along prep** — prior notes, agreed actions, and what to observe next.
  4. **Accounts / business context** — key accounts with context and mismatch flags.
  5. **Opener** — a short, editable way to start the morning conversation.
- **Primary user: the district manager (DM).** The **regional business director (RBD)**
  gets a **read-only, region-scoped** view of the same per-DM briefs.

### Out of scope (MVP / later)

- **Summit ranking optimization.**
- **Leadership theme aggregation** across districts or regions (no roll-ups).
- **Capturing notes by voice** during or after a ride.
- **Any connection to real or live data** (Veeva, IQVIA, AEBAT, Summit, etc.) — the MVP
  is synthetic-only.

### Success criteria

From the spec's measurable outcomes — these are the bar the MVP must clear:

- A DM can prepare for the conversation in **under ~5 minutes** (SC-001).
- **100% of recommendations show a reason** and the data behind them (SC-002).
- **100% of data shown is in the user's territory** — zero out-of-scope reps, accounts,
  or HCPs (SC-003).
- Preparation is **more consistent and complete** than working without the assistant,
  scored against the fixed **5-section checklist rubric** (SC-004, SC-005).
- **Every recommendation type passes its example-based checks** on seeded data, so results
  are **repeatable** (SC-006).
- **100% synthetic data** — no real customer, prescriber, or rep data anywhere (SC-007).
  A pre-commit hook actively blocks committing files that look like real data.

---

## What the MVP does (the morning coaching brief)

A DM opens the assistant on the morning of a field ride and, in a few minutes, gets a
single brief made of **five sections**:

1. **Who to ride with and why** — a short, ranked list of reps who most need attention
   today, each with a plain-language reason and the business signals behind it.
2. **What to coach this rep on** — 1–3 suggested coaching focus areas, each with its
   reason and supporting data.
3. **What happened last time (ride-along prep)** — the rep's prior coaching notes, the
   actions both sides agreed, and what the DM said they would observe next.
4. **Which accounts/HCPs matter and how the business is doing** — a focused list of key
   accounts with business context (share, volume, performance, spend, recent call
   activity) and flags where the rep's behavior may not match the opportunity.
5. **A suggested opener** — a short way to start the morning business conversation,
   referencing this rep's specific situation. A suggestion the DM can edit or ignore.

**In scope for the MVP:** these five brief sections, scoped to the user's own territory.
**Out of scope for the MVP:** Summit ranking optimization, and aggregating coaching themes
across districts/regions for leadership roll-ups.

---

## Guiding principles

These come from the project constitution (`.specify/memory/constitution.md`) and are
non-negotiable:

- **AI suggests, the human decides.** No autonomous actions — the agent never books,
  sends, commits, or executes anything on its own.
- **Always explain why.** Every recommendation surfaces its reason and the underlying data
  signals. No black-box output.
- **Synthetic data only in the POC.** Data mirrors the *shape* of real data but is fully
  fabricated and clearly labeled synthetic.
- **RBAC by territory, enforced at the data layer.** A DM sees only their own district; an
  RBD sees their region, read-only. Scope is enforced server-side, not just hidden in the
  UI.
- **Ranking is deterministic, not LLM-decided.** The rep prioritization is computed in
  code from fixed, visible weights over legitimate business signals. The LLM only turns
  the structured reason into clear language — it never decides or reorders the ranking.
- **Fair, not biased.** Protected attributes and obvious proxies (e.g. tenure) are
  excluded from the signals that drive prioritization.
- **Quality must be testable.** The five-section checklist rubric and example-based checks
  are enforced by automated tests.

---

## Architecture

Everything reads through **one data-access interface** — components never touch a store
directly. This is the seam that lets the POC swap synthetic data for real AWS-backed
connectors later without a rewrite.

```mermaid
flowchart TD
    User["DM / RBD<br/>(browser)"] --> UI["Web UI<br/>(planned)"]
    UI --> API["FastAPI app<br/>(planned)"]
    API --> Orch["LangGraph orchestrator<br/>explicit DAG, no loops<br/>(planned)"]

    Orch --> C1["1. Prioritization<br/>(planned)"]
    Orch --> C2["2. Coaching focus<br/>(planned)"]
    Orch --> C3["3. Ride-along prep<br/>(planned)"]
    Orch --> C4["4. Accounts & context<br/>(planned)"]
    Orch --> C5["5. Opener<br/>(planned)"]

    C1 --> DAL
    C2 --> DAL
    C3 --> DAL
    C4 --> DAL
    C5 --> DAL

    LLM["LLM narration<br/>Claude on Bedrock<br/>(planned)"] -.renders reason text only.-> C1
    LLM -.-> C2
    LLM -.-> C5

    DAL["Data-access interface<br/>DataAccess + Retriever + AccessContext<br/>(BUILT — the single seam)"]
    DAL --> Store["SQLite / DuckDB store<br/>structured data<br/>(BUILT)"]
    DAL --> Vec["FAISS / Chroma<br/>coaching-notes vector store<br/>(planned)"]
    Gen["Seeded synthetic generator<br/>(BUILT)"] --> Store
```

### MVP choice → production AWS service

Each MVP choice is deliberately mapped to a production AWS service, so going to production
is a change of *source/implementation behind the interface*, not a redesign.

| Concern | MVP (now) | Production (AWS) |
|---|---|---|
| Model inference & narration | Claude on **Amazon Bedrock** (model id from config) | Claude on Amazon Bedrock |
| Structured data | Local **SQLite / DuckDB** | **Aurora Postgres** / **Athena + S3** |
| Coaching-notes retrieval (RAG) | Local **FAISS / Chroma** + Bedrock (Titan) embeddings | **Bedrock Knowledge Bases** / **OpenSearch Serverless** |
| Identity & RBAC | Simulated identity → `AccessContext` | **Amazon Cognito** (+ data-layer scope) |
| PII / safety guardrail | Lightweight pass-through hook | **Bedrock Guardrails** |

---

## How a brief is produced

The flow below shows one morning brief end to end. Steps are marked **[BUILT]**
(Phase 1 foundation exists) or **[PLANNED]** (designed, not yet implemented).

```mermaid
flowchart TD
    A["DM requests today's brief<br/>[PLANNED API]"] --> B["RBAC scope check<br/>at the data-access layer<br/>[PLANNED — T008]"]
    B --> C["Read scoped synthetic data<br/>via the data-access interface<br/>[BUILT]"]
    C --> D["Deterministic prioritization<br/>fixed visible weights over 4 signals<br/>ranked reps + structured reasons<br/>[PLANNED — code, not LLM]"]
    D --> E["DM picks a rep to ride with<br/>[PLANNED]"]
    E --> F["Gather: coaching focus,<br/>ride-along prep, accounts/context, opener<br/>[PLANNED]"]
    F --> G["LLM narrates each reason<br/>into clear language<br/>(never changes ranks/scores)<br/>[PLANNED]"]
    G --> H["Assemble brief — every section<br/>carries a visible reason<br/>[PLANNED]"]
    H --> I["Show brief to DM<br/>DM decides — assistant only suggests<br/>[PLANNED UI]"]
```

What exists **today** is the spine the rest hangs on: the schemas that force every
recommendation to carry a non-empty `reason`, the data-access interface and `AccessContext`
that all reads pass through, the SQLite store, and the seeded generator that produces a
repeatable two-district synthetic dataset with varied ranking signals and edge cases.

---

## Tech stack

- **Language:** Python 3.11+
- **API:** FastAPI (planned)
- **Orchestration:** LangGraph — an explicit, code-defined DAG (no autonomous agent
  loops), so the flow stays testable and reviewable (planned)
- **LLM:** Claude on **Amazon Bedrock**; the model id is read from configuration, never
  hard-coded
- **Stores (MVP):** SQLite / DuckDB for structured data; FAISS / Chroma for the
  coaching-notes RAG
- **Validation:** Pydantic schemas (including the structured `Reason` object)
- **Tests:** pytest (unit now; component and end-to-end planned)
- **Tooling:** `uv` for environments/deps; `ruff` for lint + format

---

## How to read this repo (repository guide)

```text
field-intelligence-coach-agent/
├── README.md                       # you are here
├── CLAUDE.md                       # golden rules + stack + commands for contributors/agents
├── pyproject.toml                  # deps, pytest config, ruff config
├── .githooks/pre-commit            # blocks committing real (non-synthetic) data
├── .specify/                       # Spec Kit + the project constitution
│   └── memory/constitution.md      # the 9 non-negotiable principles
├── specs/001-morning-coaching-brief/
│   ├── spec.md                     # WHAT & WHY: user stories, requirements, success criteria
│   ├── plan.md                     # HOW: architecture, constitution check, structure
│   ├── tasks.md                    # the dependency-ordered task list (T001…T043)
│   └── checklists/                 # spec-quality checklist(s)
├── src/coach/
│   ├── schemas.py                  # BUILT — entities, Reason, recommendation objects, Dataset
│   ├── config/settings.py          # BUILT — model id (from env), seed, fixed ranking weights
│   ├── data_access/
│   │   ├── interface.py            # BUILT — DataAccess + Retriever + AccessContext + ScopeError
│   │   └── sqlite_store.py         # BUILT — structured store (RBAC enforcement is T008)
│   ├── synthetic/generate.py       # BUILT — seeded synthetic data generator (CLI)
│   ├── components/                 # placeholder — the 5 brief sections (planned)
│   ├── llm/                        # placeholder — Bedrock Claude + embeddings (planned)
│   ├── guardrails/                 # placeholder — PII guardrail seam (planned)
│   ├── orchestrator/               # placeholder — LangGraph DAG + brief assembly (planned)
│   ├── observability/              # placeholder — per-brief / per-LLM audit (planned)
│   └── api/                        # placeholder — FastAPI app (planned)
├── tests/
│   ├── unit/test_schemas.py        # BUILT — every recommendation requires a non-empty reason
│   ├── unit/test_data_access.py    # BUILT — seeded shape, determinism, synthetic provenance
│   ├── component/                  # planned — per-component tests
│   └── e2e/                        # planned — rubric, audit, synthetic-only, quickstart
└── web/                            # placeholder — minimal brief UI (planned)
```

**Recommended reading order for a newcomer:**

1. `.specify/memory/constitution.md` — the rules everything obeys.
2. `specs/001-morning-coaching-brief/spec.md` — what we're building and why.
3. `specs/001-morning-coaching-brief/plan.md` — the architecture and the AWS mapping.
4. `src/coach/schemas.py` then `src/coach/data_access/interface.py` — the data contracts
   and the single read-seam that shape all the code.
5. `src/coach/synthetic/generate.py` and `src/coach/data_access/sqlite_store.py` — how the
   synthetic data is made and stored.
6. `tests/unit/` — the behavior that is actually guaranteed today.
7. `specs/001-morning-coaching-brief/tasks.md` — exactly what is done and what is next.

---

## Engineering setup (Claude Code)

This repo ships with a small Claude Code setup that bakes the constitution into the daily
workflow: focused subagents for common jobs, two manual slash commands, and automatic
guardrails that run without anyone remembering to invoke them.

### Subagents (`.claude/agents/`)

- **`data-explorer`** — read-only investigation of the synthetic dataset and the repo
  (find files, search code, run `SELECT`-style reads). Use it to gather facts *before* a
  change without cluttering the main context; it can never write, edit, or delete. Runs on
  a **cheap/fast model (Haiku)** because the work is lookup-and-summarize, not deep
  reasoning.
- **`test-runner`** — runs `pytest -q` and reports a short pass/fail summary, naming any
  failing tests with a one-line likely cause. Use it after code changes to validate; it
  does not fix code itself. Runs on a **cheap/fast model (Haiku)** since running tests and
  summarizing output is mechanical.
- **`constitution-guardian`** — reviews proposed code or changes against the **9
  constitution principles**, flagging each issue with the file, the rule broken, and a
  concrete fix (and watching for the LLM deciding the ranking). Use it before committing a
  feature or when unsure a change is allowed. Runs on a **strong model (Opus)** because
  judging subtle principle violations needs real reasoning.

### Skills / slash commands (`.claude/skills/`)

Both are **manual-only** — they are marked `disable-model-invocation: true`, so they never
auto-run; you trigger them explicitly.

- **`/gen-synthetic-data`** — builds (or runs) the seeded synthetic data generator:
  1 region, 2 districts, 8–12 reps each, 15–30 accounts/HCPs per rep, 2–3 coaching
  sessions, with a fixed seed for repeatability and the four ranking signals varied across
  reps.
- **`/run-checklist-eval`** — runs the fixed 5-section rubric check on generated briefs: a
  brief passes only if all five sections are present and every recommendation shows a
  visible reason, plus the example-based (seeded) checks and a synthetic-only confirmation.

### Automatic guardrails (hooks)

- **Git pre-commit hook (`.githooks/pre-commit`)** — blocks any commit that stages files
  looking like real (non-synthetic) data (e.g. `data/real/`, `real_data/`, `*.real.csv`).
  It exists to enforce the **synthetic-only rule at commit time** — the last safe moment —
  so real data can never slip into the repo.
- **PostToolUse format hook (`.claude/settings.json` → `scripts/claude-format-hook.sh`)**
  — after Claude edits or writes a file, automatically runs `ruff check --fix` and
  `ruff format` on any `.py` file. It exists to keep formatting and lint consistent
  automatically, so style never has to be policed by hand in review.

**Why this matters:** these pieces enforce our constitution automatically and keep quality
consistent (operational excellence), so the project does not rely on people remembering
the rules.

---

## The spec-driven workflow we followed

This project was built spec-first to keep the rigor visible. The steps, in order:

1. **Constitution** — ratify the non-negotiable principles.
2. **Specify** — write the feature spec (user stories, requirements, success criteria).
3. **Clarify** — resolve open questions and record the answers back into the spec.
4. **Plan** — produce the technical plan and pass the Constitution Check gate.
5. **Tasks** — generate a dependency-ordered task list (T001…T043).
6. **Analyze** — cross-check spec ↔ plan ↔ tasks for consistency.
7. **Implement in small phases** — Phase 1 (foundation) first, validated by tests, before
   any component work begins.

---

## How to run it

This project uses [`uv`](https://docs.astral.sh/uv/).

```bash
# 1. Install dependencies into a local environment
uv sync

# 2. Generate the seeded synthetic dataset (repeatable; writes ./data/coach.db)
uv run python -m coach.synthetic.generate --seed 42

# 3. Run the test suite (17 tests today)
uv run pytest
```

Lint and format (optional): `uv run ruff check --fix . && uv run ruff format .`

> The API (`uvicorn coach.api.app:app --reload`) and the web UI are planned and not yet
> runnable.

---

## Phases

Honest status: **only Phase 1 is Done.** Everything else is planned. Task IDs below come
straight from `specs/001-morning-coaching-brief/tasks.md`.

### Phase 1 — Foundation · STATUS: ✅ Done

- **Goal:** the base everything else builds on.
- **Delivers:** the data-access interface (the single seam every component reads through),
  the data schema (with the required `reason` object), a local SQLite store, the seeded
  synthetic data generator (1 region, 2 districts, varied ranking signals + edge cases),
  configuration, and their tests. **17 unit tests pass.**
- **Tasks:** T001–T007, T009 (setup, config, interface, schemas, store, generator) and
  the tests T018, T019.

### Phase 2 — RBAC · STATUS: ⏳ Planned (next)

- **Goal:** enforce role + territory **at the data-access layer** — a DM sees only their
  own district; an RBD sees their whole region, read-only — and reject any out-of-scope
  request with a `ScopeError`.
- **Delivers:** RBAC scoping wired into every store read, plus its tests.
- **Tasks:** T008 (RBAC in the data layer), T017 (RBAC tests).

### Phase 3 — Deterministic ranking · STATUS: ⏳ Planned

- **Goal:** rank reps with **fixed, visible weights** over the four business signals
  (declining share, low call activity, missed follow-up, opportunity/risk). The ranking is
  computed in code; **the LLM never decides or reorders it** — it only phrases the reason.
- **Delivers:** the deterministic scorer, the separate LLM reason-narration step, and the
  `GET /api/reps` endpoint — including the **fairness test** and the
  **anti-LLM-ranking guard**.
- **Tasks:** T023 (deterministic scorer), T024 (LLM narration, text only), T025 (wire +
  `GET /api/reps`); tests T020 (scorer), T021 (golden + anti-LLM-ranking guard),
  T022 (endpoint), T022a (fairness).

### Phase 4 — Brief sections · STATUS: ⏳ Planned

- **Goal:** build the remaining brief sections (2–5), each with its build and test tasks.
- **Delivers:**
  - **Coaching focus** — 1–3 focus areas, each with a reason: T027 (build), T028 (wire),
    T026 (test).
  - **Ride-along prep** — RAG over coaching notes; empty state when no history: T030
    (build), T031 (wire), T029 (test).
  - **Accounts / business context** — key accounts, context, mismatch flags: T033 (build),
    T034 (wire), T032 (test).
  - **Opener** — short, suggestion-only opener; full `GET /api/brief/{rep_id}`: T036
    (build), T037 (wire full brief), T035 (test).

### Phase 5 — Assembly, rubric, API · STATUS: ⏳ Planned

- **Goal:** join the sections into the full brief, prove its quality, and expose it safely.
- **Delivers:** the LangGraph assembly and FastAPI app (T015 orchestrator + brief
  assembly, T016 API skeleton); the **5-section checklist rubric** plus the
  **consistency check** (T038); **privacy-in-logging** / audit (T040); the synthetic-only
  guard (T041); and end-to-end quickstart checks (T042). Then the deferred guards
  **F6** (read-only API — no write routes), **F7** (graceful degrade of the brief
  endpoint), and **F8** (RBD cannot reach a write/action path).

### Phase 6 — UI · STATUS: ⏳ Planned

- **Goal:** a simple web page that shows the brief and every reason block (suggestions
  only; the DM decides).
- **Delivers:** the minimal `web/index.html` page — T039.

---

## Data & compliance note

- **Synthetic data only** for this POC — no real Veeva, IQVIA, AEBAT, or Summit data ever
  enters the environment; synthetic data is clearly labeled (`synthetic=true`) and never
  presented as real performance.
- This is a **commercial system, not GxP** — but it is designed to be governed, secure,
  and auditable from day one.
- **HCP/prescriber data is treated as private** (IQVIA / PDRP rules) and **rep performance
  data as HR-sensitive**, in how it is scoped, displayed, and (later) logged.
- **RBAC and explainability are designed in, not bolted on:** access is enforced at the
  data layer, and every recommendation must carry its reason. Designing for the strictest
  rules now means that swapping in real data later is a data-source change, not a security
  or compliance redesign.
