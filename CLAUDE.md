# field-intelligence-coach-agent

An assistant that helps district managers (DMs) prepare for coaching their reps
and make fairer decisions about where to spend limited field time.
MVP = the "morning coaching brief" (5 sections). See
`specs/001-morning-coaching-brief/` for the spec and plan.

## Golden rules (from the project constitution — never break these)
- The assistant only SUGGESTS. The human (DM or a region-level role) always DECIDES. No autonomous actions.
- Every recommendation must show its REASON and the data behind it. No hidden logic.
- SYNTHETIC DATA ONLY. Never create, commit, or read real customer, prescriber, or rep data.
- Enforce RBAC at the data-access layer (not just the UI) by TERRITORY SCOPE LEVEL, not
  job title: self (rep) / district (DM — own district) / region (region-level roles) /
  all regions (top sales role). All non-rep roles have FULL access within their scope (not
  read-only); roles map to a scope level via a single config/enum source. Exact role names
  are config-only and pending confirmation — see `docs/project-status.md`.
- PRP scrubbing: HCPs flagged `prp` are removed at the data-access layer before any result
  reaches a field user (FR-020). Never return a PRP HCP to a field user.
- The rep prioritization RANKING is deterministic and explainable — computed in code,
  not decided by the LLM. The LLM only turns the structured reason into clear language.
- Quality must be testable: the 5-section checklist rubric is enforced by automated tests.

## Stack
- Python, FastAPI, LangGraph (orchestration in code — no autonomous agent loops).
- LLM: Claude on Amazon Bedrock. Read the model id from configuration; never hard-code it.
- MVP stores (behind a data-access interface): SQLite or DuckDB (structured data)
  and FAISS or Chroma (coaching-notes RAG). These map to Aurora/Athena and
  Bedrock Knowledge Bases / OpenSearch in production.
- Tests: pytest.

## Commands (all wired; Phases 1–10 built)
- Install deps:        `uv sync`
- Run the API:         `uvicorn coach.api.app:app --reload`  (runs offline by default; Bedrock only when configured)
- Run tests:           `pytest`
- Lint and format:     `ruff check --fix . && ruff format .`
- Generate fake data:  use the `/gen-synthetic-data` skill
- Run the rubric eval: use the `/run-checklist-eval` skill

## Conventions
- All data reads go through the data-access layer. A component never reads a store directly.
- Each brief recommendation returns a structured `reason` object the UI renders.
- Metrics are per (account, brand): share, volume, spend, and call activity are attributable
  to an (account, brand) pair (`AccountBrandMetrics`). Brand names come ONLY from the `Brand`
  enum (single source of truth) — never hard-code a brand string elsewhere.
- Keep every MVP choice mapped to a production AWS service (see the plan).

## Helpful subagents
- `data-explorer` — read-only investigation of the data and repo.
- `test-runner` — run pytest and report failures.
- `constitution-guardian` — review changes against the golden rules above.

<!-- SPECKIT START -->

<!-- SPECKIT END -->
