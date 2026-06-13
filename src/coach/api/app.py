"""T016 / T025 / T037 — the read-only FastAPI surface over the brief orchestrator.

Every endpoint is a **GET** (Principle I / FR-011: the assistant suggests, it never acts —
there is no POST/PUT/PATCH/DELETE or any write/action path). The flow is:

    X-User-Id header  ->  resolve to a User (role + territory)  ->  build an AccessContext
    (scope_level from the SINGLE config source; the caller CANNOT choose it)  ->  call the
    deterministic ranking / brief orchestrator with that context.

RBAC + PRP hold because the context threads into the data-access layer, which scopes every
read and scrubs PRP HCPs (Principle V / FR-013/014, FR-020). An out-of-scope OR unknown rep is
returned as the SAME clean `403` (FR-014 — existence is never leaked). Narrate-before-expose is
enforced by the orchestrator's assembly guard and re-checked here, so no response body can carry
a `PENDING_*` placeholder (ADR 0003). One privacy-safe audit record is emitted per request
(FR-016) — safe identifiers/metadata only, never names or metrics.

Data-access connection: a **fresh store (its own SQLite connection) is opened per request** via
a FastAPI dependency and closed when the request ends — no process-wide shared connection. This
maps to a connection pool / Aurora in production (`get_resources`).

Wiring: the LLM + embeddings providers are injected via `AppDeps` so tests run fully offline
with fakes; production uses Bedrock (model id from config — never hard-coded).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from coach.components.ranking import rank_reps
from coach.config.settings import Settings, get_settings
from coach.data_access.interface import AccessContext, ScopeError
from coach.data_access.notes_retriever import NotesRetriever
from coach.data_access.sqlite_store import SqliteStore
from coach.llm.client import LLM
from coach.llm.embeddings import EmbeddingProvider
from coach.llm.factory import make_embedder, make_llm
from coach.llm.narrate import narrate_rankings
from coach.observability import audit
from coach.orchestrator.assembly import (
    PENDING_PLACEHOLDERS,
    BriefNotNarratedError,
    assert_narrated,
)
from coach.orchestrator.brief_graph import build_brief
from coach.schemas import RepRanking, Role

_log = logging.getLogger("coach.api")

# The read-only web UI (T039). Served from the FastAPI app so it is same-origin with the GET
# API (no CORS) and adds no new data path — it is a static page that calls the GET endpoints.
_WEB_DIR = Path(__file__).resolve().parents[3] / "web"


# --------------------------------------------------------------------------- app configuration
@dataclass
class AppDeps:
    """Process-wide injectable config: how to build per-request resources. Tests override
    `llm` / `embedder` with fakes and point `db_path` at a seeded temp DB; production uses the
    lazy Bedrock seams + the configured DB path."""

    db_path: str
    settings: Settings
    llm: LLM
    embedder: EmbeddingProvider
    # How a per-request store (connection) is opened. Default: a fresh SqliteStore.
    store_factory: Callable[[str], SqliteStore] = field(default=SqliteStore)


def default_deps() -> AppDeps:
    """Default wiring + the configured DB path. The LLM / embeddings provider is chosen by the
    single factory: real Bedrock IFF its model id is configured, else the deterministic OFFLINE
    provider — so the server runs fully offline by default (no AWS) and only calls Bedrock when
    explicitly configured (model id from config). Both Bedrock clients construct lazily, so this
    never makes a network call at import time."""
    s = get_settings()
    return AppDeps(
        db_path=s.db_path,
        settings=s,
        llm=make_llm(s),
        embedder=make_embedder(s),
    )


class RequestResources:
    """Per-request data-access resources, owning ONE store connection for this request.

    The notes retriever is built lazily (only the brief endpoint needs it) on the SAME
    per-request connection."""

    def __init__(self, store: SqliteStore, deps: AppDeps) -> None:
        self.store = store
        self._deps = deps
        self._retriever: NotesRetriever | None = None

    def retriever(self) -> NotesRetriever:
        if self._retriever is None:
            r = NotesRetriever(self.store, self._deps.embedder)
            r.index()
            self._retriever = r
        return self._retriever


# --------------------------------------------------------------------------------- dependencies
def get_deps(request: Request) -> AppDeps:
    return request.app.state.deps


def get_resources(request: Request) -> Iterator[RequestResources]:
    """Open a FRESH store (its own connection) for this request; close it when the request ends.

    Per-request connection (not a process-wide shared one) — maps to a connection pool / Aurora
    in production. FastAPI caches this dependency within a request, so identity resolution and
    the endpoint share the one connection, and it is always closed in `finally`."""
    deps = get_deps(request)
    store = deps.store_factory(deps.db_path)
    try:
        yield RequestResources(store, deps)
    finally:
        store.close()


def get_access_context(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    resources: RequestResources = Depends(get_resources),
) -> AccessContext:
    """Resolve the caller's identity into an `AccessContext`.

    The scope level is derived from the role via the single config source
    (`AccessContext.__post_init__` → `scope_level_for`) — the caller never chooses their own
    scope or rep set. Missing/unknown identity → `401` (per the api.md contract)."""
    if not x_user_id:
        raise HTTPException(status_code=401, detail="missing identity")
    user = resources.store.get_user(x_user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="unknown identity")
    return AccessContext(
        user_id=user.user_id,
        role=user.role,
        region_id=user.region_id,
        district_id=user.district_id,
        # self-scope (a rep) is keyed by rep_id; non-rep roles leave it None.
        rep_id=(user.user_id if user.role == Role.rep else None),
        # scope_level intentionally omitted -> derived from role via config (not caller input).
    )


# --------------------------------------------------------------------- narrate-before-expose
def _assert_rankings_narrated(rankings: list[RepRanking]) -> None:
    """Re-check the orchestrator invariant at the API boundary: a ranking summary must never be
    an un-narrated placeholder before it is exposed (ADR 0003)."""
    bad = [r.rep_id for r in rankings if r.reason.summary in PENDING_PLACEHOLDERS]
    if bad:
        raise BriefNotNarratedError(
            "narrate-before-expose: un-narrated ranking(s): " + ", ".join(bad)
        )


# ----------------------------------------------------------------------- stale-schema guard
def _verify_db_schema(deps: AppDeps) -> None:
    """Fail fast with a CLEAR message if the configured on-disk DB predates the current schema,
    instead of a cryptic downstream `IndexError` when a read hits a column an old DB lacks.

    Synthetic-only: we DETECT a stale DB and tell the user to regenerate — there are no
    migrations. Skipped for an in-memory or not-yet-created DB (the generator stamps the current
    version on creation); skipped for an empty file (the generator will populate + stamp it)."""
    path = deps.db_path
    if path == ":memory:" or not Path(path).exists():
        return
    store = deps.store_factory(path)
    try:
        if store.has_schema():
            store.require_current_schema()  # raises SchemaVersionError with the regenerate hint
    finally:
        store.close()


# --------------------------------------------------------------------------------- the app
def create_app(deps: AppDeps | None = None) -> FastAPI:
    """Build the read-only API. Pass `deps` (with fakes) in tests; omit for production."""
    resolved = deps or default_deps()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Guard at SERVER startup (uvicorn / `with TestClient(app)`): a stale on-disk DB fails
        # loudly here — before any request — rather than mid-read. Importing the module (and the
        # module-level `app = create_app()`) does NOT run this, so a stale DB never breaks import.
        _verify_db_schema(resolved)
        yield

    app = FastAPI(
        title="Field Intelligence Coach — read-only brief API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.deps = resolved

    # --- error mapping: clean status codes, never a stack trace or sensitive detail ---
    @app.exception_handler(ScopeError)
    async def _scope_handler(request: Request, exc: ScopeError) -> JSONResponse:
        # Out-of-scope AND not-found both land here as the SAME 403 (FR-014 — no existence leak).
        return JSONResponse(status_code=403, content={"detail": "forbidden"})

    @app.exception_handler(KeyError)
    async def _keyerror_handler(request: Request, exc: KeyError) -> JSONResponse:
        # A missing in-scope rep_id — kept indistinguishable from out-of-scope (FR-014).
        return JSONResponse(status_code=403, content={"detail": "forbidden"})

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internals (stack trace / message) to the client (FR-016 defense-in-depth).
        _log.error("unhandled error on %s %s: %s", request.method, request.url.path, type(exc))
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    # ------------------------------------------------------------------------ endpoints
    @app.get("/api/whoami")
    def whoami(ctx: AccessContext = Depends(get_access_context)) -> dict:
        """Echo the resolved access context (role + territory) for the UI."""
        return {
            "user_id": ctx.user_id,
            "role": ctx.role.value,
            "scope_level": ctx.scope_level.value,
            "district_id": ctx.district_id,
            "region_id": ctx.region_id,
        }

    @app.get("/api/reps")
    def list_reps(
        limit: int | None = Query(default=None, ge=1, le=50),
        ctx: AccessContext = Depends(get_access_context),
        resources: RequestResources = Depends(get_resources),
        deps: AppDeps = Depends(get_deps),
    ) -> dict:
        """Brief section 1: the ranked reps needing attention, scoped to the caller.

        Deterministic ranking in code; the LLM only narrates each reason. RBAC is enforced in
        the data-access layer, so the list contains only in-scope reps (FR-013/014)."""
        n = limit or deps.settings.ranked_reps_max
        full = rank_reps(ctx, resources.store, deps.settings)
        ranked = narrate_rankings(full[:n], deps.llm)
        _assert_rankings_narrated(ranked)  # no placeholder may reach the client
        audit.audit("list_reps", ctx, limit=n, ranked_count=len(ranked))
        return {
            "synthetic": True,
            "scope": {
                "role": ctx.role.value,
                "scope_level": ctx.scope_level.value,
                "district_id": ctx.district_id,
            },
            "ranked_reps": [r.model_dump() for r in ranked],
        }

    @app.get("/api/brief/{rep_id}")
    def get_brief(
        rep_id: str,
        ctx: AccessContext = Depends(get_access_context),
        resources: RequestResources = Depends(get_resources),
        deps: AppDeps = Depends(get_deps),
    ) -> dict:
        """The full 5-section coaching brief for one in-scope rep (suggestion-only data).

        `403` if `rep_id` is outside the caller's scope (or does not exist — indistinguishable,
        FR-014). The orchestrator threads the context through every section (RBAC + PRP hold)
        and enforces narrate-before-expose; we re-assert it here before returning."""
        brief = build_brief(
            ctx,
            resources.store,
            resources.retriever(),
            deps.llm,
            rep_id=rep_id,
            settings=deps.settings,
        )
        assert_narrated(brief)  # belt-and-suspenders: no placeholder may reach the client
        audit.audit(
            "generate_brief",
            ctx,
            brief_id=brief.brief_id,
            selected_rep_id=brief.selected_rep_id,
            ranked_count=len(brief.ranked_reps),
            accounts_count=len(brief.accounts),
        )
        return brief.model_dump()

    # --------------------------------------------------------------------- the web UI (T039)
    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        """Serve the minimal read-only brief page. It is a static page that calls only the GET
        API above (no write/action controls — FR-011) and renders exactly what the API returns
        (no client-side ranking/recompute)."""
        return HTMLResponse((_WEB_DIR / "index.html").read_text(encoding="utf-8"))

    return app


# Module-level ASGI app for `uvicorn coach.api.app:app --reload`. Import-safe: production deps
# build the Bedrock clients lazily (no AWS config needed merely to import this module).
app = create_app()
