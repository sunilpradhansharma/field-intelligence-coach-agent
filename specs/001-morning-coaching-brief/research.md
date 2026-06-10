# Phase 0 Research: Morning Coaching Brief (MVP)

This resolves the open/deferred items from the spec and the technology choices from the
plan input. Each decision records **Decision / Rationale / Alternatives / Production
mapping** so the POC can grow into a governed AWS system without a rewrite (Principle VII).

## 1. Orchestration — LangGraph, explicit DAG (no autonomous loops)

- **Decision**: A single LangGraph `StateGraph` wires the five components as an explicit
  directed acyclic graph: `prioritize → (focus, ride_along, accounts) → opener → assemble`.
  No cycles, no self-directed tool selection. Components are plain Python callables today;
  each is shaped so it can later become its own subagent node.
- **Rationale**: Constitution I & VIII — flow must be explicit and testable, and no fully
  autonomous agent loops. A DAG is deterministic, traceable, and unit-testable per node.
- **Alternatives**: A free-running ReAct/agent loop (rejected: not explainable/testable,
  violates "no autonomous loops"); plain function calls with no graph (rejected: loses the
  clean per-node boundary that enables the future subagent split and per-node tracing).
- **Production mapping**: Same LangGraph code runs in a container on AWS (ECS/Fargate or
  Lambda); nodes can be promoted to Bedrock Agents/subagents behind the same interfaces.

## 2. LLM access — Claude on Amazon Bedrock, model id from config

- **Decision**: A thin `llm/` wrapper calls Bedrock via `boto3`. The Claude model id and
  AWS region are read from configuration/environment (e.g., `BEDROCK_MODEL_ID`,
  `AWS_REGION`) — never hard-coded. Default points to the latest Claude model approved for
  use at AbbVie. The LLM is used only to (a) narrate structured reason objects into clear
  language, (b) propose coaching focus phrasing, and (c) draft the opener. It never
  computes rankings.
- **Rationale**: Constitution VIII (one platform) and the explicit instruction to avoid a
  hard-coded model id. Keeping the LLM out of ranking preserves Principle VI (fair, not
  biased) and II (exact, reproducible reasons).
- **Alternatives**: Hard-coded model id (rejected: brittle, blocks approved-model swaps);
  letting the LLM rank reps (rejected: non-deterministic, unexplainable, unfair).
- **Production mapping**: Same Bedrock runtime; add Bedrock Guardrails + provisioned
  throughput; model id still config-driven.

## 3. Rep prioritization — deterministic, explainable scorer

- **Decision**: A pure Python scoring function ranks reps using the four signals
  (declining share, low call activity in key accounts, missed coaching follow-up,
  business opportunity/risk). Each signal is normalized to a 0–1 sub-score; the total is a
  weighted sum with **fixed, visible weights** loaded from config. The function returns a
  ranked list plus, per rep, a `reason` object listing each signal's value, weight,
  contribution, and the underlying data points. Ties are broken by a documented, stable
  rule (e.g., higher opportunity/risk first, then rep id) so ordering is never hidden.
- **Rationale**: Constitution II & VI — ranking must be explainable, reproducible, and
  free of hidden criteria. Determinism also makes seeded example-based tests possible (IX).
- **Alternatives**: LLM-judged ranking (rejected, see §2); ML model (rejected for MVP:
  opacity, fairness risk, no training data). Initial weights are equal/sensible defaults,
  documented and tunable; weighting is shown to the user.
- **Production mapping**: Same function; weights become a governed, versioned config; can
  later read richer signals from real connectors through the unchanged data interface.

## 4. Data-access interface & structured store

- **Decision**: One `DataAccess` abstract interface exposes read methods (reps, accounts,
  activity, share/volume/spend, opportunity/risk, coaching sessions). The MVP
  implementation is backed by **SQLite** (default; DuckDB acceptable) loaded from the
  seeded synthetic generator. Every component depends on the interface, never on the store.
- **Rationale**: Constitution VII — swapping synthetic for real data must be a source
  change, not a rewrite. SQLite is zero-infra and repeatable for tests.
- **Alternatives**: Components query the DB directly (rejected: couples logic to storage);
  Postgres locally (rejected: unnecessary infra for the MVP).
- **Production mapping**: `sqlite_store` → Aurora Postgres implementation, or Athena/S3
  for columnar analytics — same interface, swapped implementation.

## 5. Coaching notes RAG — embeddings + local vector store

- **Decision**: Coaching notes are chunked, embedded with **Amazon Titan Embeddings**
  (via the Bedrock wrapper), and indexed in a local **FAISS** store (Chroma acceptable)
  behind a `Retriever` interface. Ride-along prep retrieves the most recent/relevant notes,
  agreed actions, and "observe next" items for the selected rep, filtered by RBAC scope.
- **Rationale**: Section 3 of the brief is retrieval over notes; using Bedrock embeddings
  now keeps the embedding path production-identical (VII, VIII).
- **Alternatives**: Keyword search only (rejected: weaker recall on free-text notes);
  hosted vector DB for MVP (rejected: unnecessary infra).
- **Production mapping**: `faiss_retriever` → Amazon Bedrock Knowledge Bases or OpenSearch
  Serverless — same `Retriever` interface.

## 6. RBAC — enforced in the data-access layer

- **Decision**: An RBAC filter sits **inside** the data-access layer. Every read is scoped
  by the caller's `AccessContext` **scope level**, not job title: `self` (rep — modeled, no
  MVP workflow), `district` (DM — own district), `region` (region-level roles, e.g. RD/RBE —
  all districts in their region), `all` (top sales role — all regions). All non-rep levels
  have **full access** (including actions), not read-only; the role-name → scope-level
  mapping comes from a single config source. Out-of-scope rows are excluded from results,
  not merely hidden in the UI, and an out-of-scope read raises `ScopeError`.
- **Rationale**: Constitution V — scope must be enforced server-side at the data layer so
  the model never even sees out-of-scope data. Two districts in one region exist precisely
  to test this.
- **Alternatives**: UI-only filtering (rejected: leaks data, violates V); per-component
  checks (rejected: easy to miss one — centralize in the data layer).
- **Production mapping**: `AccessContext` is populated from **Amazon Cognito** identity
  (role + territory claims) in production; in the MVP it is simulated via a selectable test
  user / header.

## 7. Authentication / identity (deferred-from-spec, resolved here)

- **Decision**: For the MVP, identity is **simulated**: the API accepts a selected test
  user (e.g., a `X-User-Id` header or a login-stub endpoint) that resolves to a role +
  territory `AccessContext`. No real password store. The `AccessContext` is the single
  source RBAC consumes.
- **Rationale**: Auth mechanism was intentionally deferred from the spec as plan-level.
  Simulating it keeps the MVP lean while exercising the real RBAC path (V).
- **Alternatives**: Full auth provider in the MVP (rejected: scope creep); no identity at
  all (rejected: cannot test RBAC).
- **Production mapping**: Amazon Cognito (user pools, role/territory claims) → populates the
  same `AccessContext`. No component change required.

## 8. Observability & audit (deferred-from-spec, resolved here)

- **Decision**: An `observability/` module emits a structured audit record for **each
  brief generation** (who, role, territory scope, rep selected, timestamp, brief id) and
  **each LLM call** (model id, purpose, input/output token counts, latency, no raw PII).
  Logs are JSON lines locally for the MVP. Audit records must not themselves leak
  out-of-scope data.
- **Rationale**: Constitution IV & VII — the system must be auditable from day one even on
  synthetic data.
- **Alternatives**: No logging in MVP (rejected: auditability is a constitution gate);
  verbose logging of full prompts incl. data (rejected: privacy risk even on synthetic).
- **Production mapping**: → Amazon CloudWatch / structured logs + traces; LLM-call logs
  align with Bedrock model-invocation logging.

## 9. PII guardrail hook

- **Decision**: A `guardrails/` step wraps inputs/outputs to/from the LLM with a
  lightweight PII check/redaction hook. In the MVP (synthetic data) it is a pass-through
  with the integration point in place and tested.
- **Rationale**: Constitution IV — keep the guardrail seam present so production simply
  swaps the implementation.
- **Production mapping**: → **Amazon Bedrock Guardrails** (PII filters, denied topics).

## 10. Testing & the fixed checklist rubric

- **Decision**: pytest at three levels: **unit** (scorer math + fixed weights, RBAC
  filter, reason-object schema, guardrail hook), **component** (each of the 5 components
  against seeded data), **e2e** (full brief). The **fixed checklist rubric** is encoded as
  an automated test: a brief passes only if all 5 sections are present AND each carries a
  visible reason. **Example-based checks** assert that, for a known seeded input, the
  ranked list and reason objects match expected output exactly (repeatable because data is
  seeded).
- **Rationale**: Constitution IX and spec SC-004/005/006. Determinism (seed + deterministic
  scorer) is what makes golden-output assertions reliable.
- **Alternatives**: Manual QA only (rejected: not repeatable, can't show leadership
  reliability); snapshot-only of LLM text (rejected: LLM phrasing varies — assert on the
  structured reason objects and rubric, not on exact LLM wording).
- **Production mapping**: Same test suite runs in CI on AWS; example fixtures expand as
  real-shaped synthetic data grows.

## 11. UI

- **Decision**: A single minimal web page (`web/index.html`) calls the FastAPI brief
  endpoint and renders the five sections, each with its reason block expandable/visible.
  No SPA framework for the MVP.
- **Rationale**: Spec asks for a simple page; keep the MVP lean. Reasons must be rendered
  (II).
- **Production mapping**: Can be replaced by a richer front end against the same API.

## Resolved unknowns summary

| Item | Status |
|------|--------|
| Ranking signals & weighting | Resolved (clarify §1) — deterministic, fixed visible weights |
| Preparedness rubric | Resolved (clarify) — fixed checklist, encoded as test |
| Region-level role scope | Resolved (clarify) — region scope, full access (not read-only), no roll-up |
| Synthetic data scale | Resolved (clarify) — 1 region / 2 districts / 8–12 reps |
| Authentication/identity | Resolved here (§7) — simulated → Cognito |
| Audit/observability scope | Resolved here (§8) — per-brief + per-LLM-call audit logs |

No `NEEDS CLARIFICATION` items remain. Proceed to Phase 1.
