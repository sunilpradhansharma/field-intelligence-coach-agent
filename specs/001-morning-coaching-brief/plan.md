# Implementation Plan: Morning Coaching Brief (MVP)

**Branch**: `001-morning-coaching-brief` | **Date**: 2026-06-07 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-morning-coaching-brief/spec.md`

## Summary

Build an MVP assistant that generates a single **morning coaching brief** for a district
manager (DM). One LangGraph orchestrator (explicit, code-defined flow — no autonomous
agent loops) produces the brief by calling five specialist components mapped to the five
spec sections. All components read through one **data-access interface** (synthetic
SQLite/DuckDB + local FAISS vector store for the MVP; the same interface maps to Aurora
Postgres / Athena-S3 and Bedrock Knowledge Bases in production). Rep prioritization is a
**deterministic, explainable scoring function** with fixed visible weights — the LLM
(Claude on Amazon Bedrock, model id read from configuration) only renders reason objects
into clear language and writes the opener; it never decides rankings. Every recommendation
carries a structured `reason` object (signals, weights, data points) that the UI renders.
RBAC (DM = own district; RBD = whole region, read-only) is enforced in the data-access
layer. A FastAPI backend serves the brief to a minimal web page. Quality is proven with
pytest at unit/component/end-to-end levels, including the fixed checklist rubric and
seeded example-based checks.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: FastAPI (API), LangGraph (code-defined orchestration),
`boto3` / AWS SDK for Amazon Bedrock (Claude inference + Titan embeddings), DuckDB or
SQLite (structured store), FAISS or Chroma (local vector store), Pydantic (schemas /
reason objects), pytest (testing). UI: minimal server-rendered HTML/JS page (no heavy
framework for the MVP).

**Storage**:
- Structured (reps, accounts, activity, share, volume, spend, opportunity/risk):
  local SQLite/DuckDB behind the data-access interface → maps to Aurora Postgres or
  Athena/S3 in production.
- Coaching notes (RAG): local FAISS/Chroma vector store with Bedrock (Titan) embeddings
  behind a retrieval interface → maps to Bedrock Knowledge Bases / OpenSearch Serverless.

**Testing**: pytest — unit (scoring function, RBAC filter, reason objects), component
(each of the 5 components), end-to-end (full brief against seeded data + rubric).

**Target Platform**: AWS (POC runs locally/containerized; deploys to AWS). LLM via
Amazon Bedrock. Model id is read from configuration — never hard-coded.

**Project Type**: Web service (FastAPI backend) + minimal web UI + orchestration library.

**Performance Goals**: Brief generation completes well within the DM's "few minutes"
goal (SC-001: full brief reviewable in < 5 minutes). Target brief assembly latency
≤ ~10s p95 for one rep on the synthetic dataset (LLM rendering dominates; deterministic
scoring is sub-second).

**Constraints**: Synthetic data only (no real Veeva/IQVIA/AEBAT/Summit). HCP data
treated as private (IQVIA/PDRP), rep data as HR-sensitive — designed in from day one.
RBAC enforced server-side at the data layer. Every recommendation must carry a
structured reason. No autonomous actions; LLM never decides rankings. Commercial (not
GxP) but governed, secure, auditable. Model id from config.

**Scale/Scope**: Synthetic: 1 region, 2 districts, 1 DM/district, 8–12 reps/district,
15–30 accounts-HCPs/rep, 2–3 prior coaching sessions/most reps. Seeded + repeatable.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | How this plan complies | Status |
|---|-----------|------------------------|--------|
| I | Human Decides, AI Assists | Output is a brief of suggestions only; no booking/sending/committing. No autonomous LangGraph loops — flow is a fixed DAG. | ✅ |
| II | Always Explain Why | Every component emits a structured `reason` object (signals, weights, data points); UI renders it. Deterministic scorer makes ranking reasons exact. | ✅ |
| III | Synthetic Data Only (POC) | Seeded synthetic generator; no real connectors. Data labeled synthetic. | ✅ |
| IV | Privacy & Compliance From Day One | HCP=private (IQVIA/PDRP), rep=HR-sensitive classifications applied to access, display, logging; PII guardrail hook present. | ✅ |
| V | RBAC | Role+territory enforced inside the data-access layer (not UI-only): DM=own district, RBD=region read-only. Two districts exist to test it. | ✅ |
| VI | Fair, Not Biased | Ranking is deterministic with fixed, visible weights over four business signals; no protected attributes/proxies; LLM cannot reorder. | ✅ |
| VII | Built to Grow Into Production | Clean data-access + retrieval + LLM + embeddings interfaces; each MVP choice has a documented AWS production mapping; source swap ≠ rewrite. | ✅ |
| VIII | One Platform (AWS+Bedrock+Claude) | Claude on Bedrock (model id from config), Titan embeddings, orchestration in code via LangGraph. | ✅ |
| IX | Quality Must Be Testable | pytest unit/component/e2e; rubric encoded as automated test; seeded example-based checks for ranking + reasons. | ✅ |

**Result**: PASS — no violations. The Complexity Tracking table below is therefore empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-morning-coaching-brief/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (API + component + data-access contracts)
│   ├── api.md
│   ├── components.md
│   └── data-access.md
├── checklists/
│   └── requirements.md  # Spec quality checklist (from /speckit-specify)
└── tasks.md             # Created by /speckit-tasks (NOT here)
```

### Source Code (repository root)

```text
src/
└── coach/
    ├── config/              # settings: Bedrock model id, region, weights, paths (no hard-coded model id)
    ├── data_access/         # CLEAN INTERFACE all components call
    │   ├── interface.py     # abstract DataAccess (structured reads) + Retriever (notes RAG)
    │   ├── sqlite_store.py    # MVP structured impl (SQLite/DuckDB) -> prod: Aurora/Athena
    │   ├── faiss_retriever.py # MVP vector impl (FAISS/Chroma) -> prod: Bedrock KB/OpenSearch
    │   └── rbac.py          # role+territory scoping enforced HERE (data layer)
    ├── synthetic/           # seeded synthetic data generator + seed loader
    ├── llm/                 # Bedrock client wrapper (Claude render + Titan embeddings), model id from config
    ├── guardrails/          # PII guardrail hook (lightweight in MVP) -> prod: Bedrock Guardrails
    ├── components/          # the 5 specialist components (each future-subagent-shaped)
    │   ├── prioritization.py  # section 1: DETERMINISTIC scorer + reason object (LLM only narrates)
    │   ├── coaching_focus.py  # section 2
    │   ├── ride_along_prep.py # section 3 (RAG over notes)
    │   ├── accounts_context.py# section 4
    │   └── opener.py        # section 5
    ├── orchestrator/        # LangGraph graph wiring the components into the brief
    │   ├── graph.py
    │   └── brief.py         # Brief assembly + structured reason aggregation
    ├── observability/       # tracing/logging of each brief + each LLM call (audit)
    └── api/                 # FastAPI app
        └── app.py          # GET brief endpoint(s); applies RBAC via authenticated identity

web/                         # minimal web page that renders the brief + reasons
└── index.html

tests/
├── unit/                   # scorer, weights, rbac filter, reason schema, guardrail hook
├── component/              # each of the 5 components against seeded data
└── e2e/                    # full brief + rubric checklist + example-based expected outputs
```

**Structure Decision**: Web-service layout. The `src/coach` package keeps every external
dependency behind an interface (`data_access`, `llm`, `guardrails`) so production swaps
are configuration/implementation changes, not rewrites (Principle VII). The five
components live under `components/` and are deliberately shaped so each can later be
promoted to its own subagent, while the MVP keeps them as plain callables wired by one
explicit LangGraph DAG.

## Complexity Tracking

> No constitution violations — no entries required.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (none)    | —          | —                                   |
