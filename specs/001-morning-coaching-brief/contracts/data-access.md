# Contract: Data-Access & Retrieval Interfaces

The single seam that lets us swap synthetic data for real connectors without rewriting
components (Principle VII). **Every** component depends on these interfaces, never on a
concrete store. RBAC is enforced **here** (Principle V).

## AccessContext

```python
@dataclass(frozen=True)
class AccessContext:
    user_id: str
    role: str                                          # role NAME (from config; maps to a scope_level)
    scope_level: Literal["self", "district", "region", "all"]
    district_id: str | None                            # set for a district-level user (a DM)
    region_id: str                                     # the user's region ("all" spans all regions)
```

- Access is scoped by **level**, not job title: `self` (rep — modeled, no MVP workflow),
  `district` (DM — own district), `region` (region-level roles, e.g. RD/RBE — whole region),
  `all` (top sales role — all regions). All **non-rep** levels have **full access (including
  actions)**, not read-only. The **role-name → `scope_level` mapping comes from a single
  config source** (role names are configuration, not hard-coded logic).
- The store is constructed/called with an `AccessContext`. All reads filter to the caller's
  `scope_level`: `district` → `district_id`; `region` → all districts in `region_id`; `all`
  → all regions; `self` → own rep. Out-of-scope rows are excluded (not merely hidden in the
  UI), and an out-of-scope read raises `ScopeError`.
- *(The earlier `read_only` flag is being retired with the scope-level model in T008 — no
  non-rep role is read-only.)*

## DataAccess (structured reads)

```python
class DataAccess(Protocol):
    def get_reps(self, ctx: AccessContext) -> list[Rep]: ...
    def get_rep(self, ctx: AccessContext, rep_id: str) -> Rep:        # raises ScopeError if out of scope
    def get_accounts(self, ctx: AccessContext, rep_id: str) -> list[Account]: ...
    def get_call_activity(self, ctx: AccessContext, rep_id: str) -> list[CallActivity]: ...
    def get_business_metrics(self, ctx: AccessContext, rep_id: str) -> list[BusinessMetric]: ...
    def get_coaching_sessions(self, ctx: AccessContext, rep_id: str) -> list[CoachingSession]: ...
```

- **MVP impl**: `SqliteDataAccess` (SQLite/DuckDB over seeded synthetic data).
- **Prod impl**: `AuroraDataAccess` / `AthenaDataAccess` — same Protocol.
- **Contract guarantees**:
  - Never returns rows outside the caller's `scope_level` (unit-tested with the 2-district seed).
  - `get_rep` / `get_*` for an out-of-scope `rep_id` raise `ScopeError` (→ API `403`).
  - **PRP scrubbing**: HCPs flagged `prp = true` (and their dependent brand-metric /
    call-activity rows) are removed before any result is returned, so no PRP HCP ever
    reaches a field user (FR-020).
  - This interface exposes **reads only** — no write/mutation methods (Principle I); any
    future write/action paths for non-rep roles live outside this read seam.

## Retriever (coaching-notes RAG)

```python
class Retriever(Protocol):
    def search_notes(self, ctx: AccessContext, rep_id: str, query: str, k: int = 4
    ) -> list[NoteChunk]: ...
```

- **MVP impl**: `FaissRetriever` (FAISS/Chroma index of Titan-embedded note chunks).
- **Prod impl**: `BedrockKnowledgeBaseRetriever` / `OpenSearchRetriever` — same Protocol.
- **Contract guarantees**: results are restricted to notes for in-scope reps only.

## Embeddings & LLM (provider seam)

```python
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...   # MVP+prod: Bedrock Titan

class LLM(Protocol):
    def narrate(self, reason_input: dict, instruction: str) -> str: ...  # render reason → prose
    def draft_opener(self, brief_context: dict) -> str: ...
```

- **Model id is read from config** (never hard-coded). `LLM` is used only to narrate
  reasons / phrase focus / draft the opener — it MUST NOT compute or alter rankings
  (Principles II, VI).

## Guardrail (PII seam)

```python
class Guardrail(Protocol):
    def scrub(self, text: str) -> str: ...   # MVP: pass-through; prod: Bedrock Guardrails
```

## Production mapping summary

| Interface | MVP impl | Production impl |
|-----------|----------|-----------------|
| DataAccess | SQLite/DuckDB | Aurora Postgres / Athena+S3 |
| Retriever | FAISS/Chroma | Bedrock Knowledge Bases / OpenSearch Serverless |
| Embedder | Bedrock Titan | Bedrock Titan (unchanged) |
| LLM | Bedrock Claude (config id) | Bedrock Claude (config id, +Guardrails) |
| Guardrail | pass-through hook | Amazon Bedrock Guardrails |
| AccessContext source | simulated user/header | Amazon Cognito claims |
