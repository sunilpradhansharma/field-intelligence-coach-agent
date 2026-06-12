"""T015 — the brief orchestrator: a FIXED LangGraph DAG (no loops) that composes the five
section components into one `CoachingBrief` (ADR 0003).

Node order (deterministic):
    rank_reps -> select_rep -> {coaching_focus, ride_along_prep, accounts_context}  (parallel)
              -> opener  (built from coaching focus + accounts + the selected rep's priority)
              -> assemble  (build CoachingBrief, then run the narrate-before-expose guard)

Each node calls its existing section component's deterministic build AND its `narrate_*`
function (with the injected LLM), so the facts stay code-decided and the section is narrated
inside the graph. The caller's `AccessContext` threads through every node — RBAC scope + PRP
scrubbing hold for every read and scope is never widened. The brief is pure data
(suggestion-only, FR-011). Tests inject fake LLM/embeddings; production uses Bedrock via config.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from coach.components.accounts_context import accounts_context_for_rep
from coach.components.coaching_focus import coaching_focus_for_rep
from coach.components.opener import build_opener
from coach.components.ranking import rank_reps
from coach.components.ride_along_prep import ride_along_prep_for_rep
from coach.config.settings import Settings, get_settings
from coach.data_access.interface import AccessContext, DataAccess, Retriever, ScopeError
from coach.llm.client import LLM
from coach.llm.narrate import (
    narrate_account_focuses,
    narrate_focuses,
    narrate_opener,
    narrate_ranking,
    narrate_rankings,
    narrate_ride_along,
)
from coach.orchestrator.assembly import assert_narrated
from coach.schemas import (
    AccountFocus,
    CoachingBrief,
    CoachingFocus,
    EmptyState,
    GeneratedFor,
    Opener,
    RepRanking,
    RideAlongPrep,
    ScopeLevel,
)


class BriefState(TypedDict, total=False):
    # Inputs (constant; never re-written by a node).
    ctx: AccessContext
    data: DataAccess
    retriever: Retriever
    llm: LLM
    settings: Settings
    rep_id: str | None  # explicit selection, or None -> the top-ranked rep
    # Intermediate / outputs.
    ranked_full: list[RepRanking]  # full in-scope ranking (for selection)
    ranked_reps: list[RepRanking]  # section 1, top-N, narrated
    selected_rep_id: str
    selected_ranking: RepRanking  # the selected rep's narrated ranking (for the opener)
    coaching_focus: list[CoachingFocus]
    ride_along_prep: RideAlongPrep | EmptyState
    accounts: list[AccountFocus]
    opener: Opener
    brief: CoachingBrief


def _scope_of(ctx: AccessContext) -> str:
    if ctx.scope_level == ScopeLevel.district:
        return ctx.district_id or ""
    if ctx.scope_level == ScopeLevel.region:
        return ctx.region_id
    if ctx.scope_level == ScopeLevel.self_:
        return ctx.rep_id or ""
    return "all"


# --------------------------------------------------------------------------------- nodes
def _rank_node(state: BriefState) -> dict:
    s = state["settings"]
    full = rank_reps(state["ctx"], state["data"], s)
    top = narrate_rankings(full[: s.ranked_reps_max], state["llm"])
    return {"ranked_full": full, "ranked_reps": top}


def _select_node(state: BriefState) -> dict:
    full = state["ranked_full"]
    if not full:
        raise ValueError("no in-scope reps to build a brief for")
    by_id = {r.rep_id: r for r in full}
    rep_id = state.get("rep_id")
    if rep_id is None:
        rep_id = full[0].rep_id  # default: the top-ranked rep
    elif rep_id not in by_id:
        # An explicit out-of-scope rep is not in the (already RBAC-scoped) ranking.
        raise ScopeError(f"rep {rep_id!r} is not in the caller's in-scope ranking")
    return {
        "selected_rep_id": rep_id,
        "selected_ranking": narrate_ranking(by_id[rep_id], state["llm"]),
    }


def _coaching_focus_node(state: BriefState) -> dict:
    cf = coaching_focus_for_rep(
        state["ctx"], state["data"], state["selected_rep_id"], state["settings"]
    )
    return {"coaching_focus": narrate_focuses(cf, state["llm"])}


def _ride_along_node(state: BriefState) -> dict:
    rap = ride_along_prep_for_rep(
        state["ctx"], state["data"], state["retriever"], state["selected_rep_id"], state["settings"]
    )
    return {"ride_along_prep": narrate_ride_along(rap, state["llm"])}


def _accounts_node(state: BriefState) -> dict:
    ac = accounts_context_for_rep(
        state["ctx"], state["data"], state["selected_rep_id"], state["settings"]
    )
    return {"accounts": narrate_account_focuses(ac, state["llm"])}


def _opener_node(state: BriefState) -> dict:
    # Built AFTER coaching focus + accounts (LangGraph fan-in waits for both).
    op = build_opener(
        state["selected_ranking"], state["coaching_focus"], state["accounts"], state["settings"]
    )
    return {"opener": narrate_opener(op, state["llm"])}


def _assemble_node(state: BriefState) -> dict:
    ctx = state["ctx"]
    brief = CoachingBrief(
        brief_id=f"brief_{state['selected_rep_id']}",
        generated_for=GeneratedFor(
            user_id=ctx.user_id, role=ctx.role, scope_level=ctx.scope_level, scope=_scope_of(ctx)
        ),
        ranked_reps=state["ranked_reps"],
        selected_rep_id=state["selected_rep_id"],
        coaching_focus=state["coaching_focus"],
        ride_along_prep=state["ride_along_prep"],
        accounts=state["accounts"],
        opener=state["opener"],
    )
    assert_narrated(brief)  # narrate-before-expose guard — RAISES on any placeholder
    return {"brief": brief}


# --------------------------------------------------------------------------------- graph
def _build_graph():
    g = StateGraph(BriefState)
    g.add_node("rank", _rank_node)
    g.add_node("select", _select_node)
    g.add_node("coaching_focus", _coaching_focus_node)
    g.add_node("ride_along", _ride_along_node)
    g.add_node("accounts", _accounts_node)
    g.add_node("opener", _opener_node)
    g.add_node("assemble", _assemble_node)

    g.add_edge(START, "rank")
    g.add_edge("rank", "select")
    # Fan-out: the three section nodes are independent and run in parallel.
    g.add_edge("select", "coaching_focus")
    g.add_edge("select", "ride_along")
    g.add_edge("select", "accounts")
    # Fan-in JOINS (list sources = wait for ALL): the opener waits for coaching focus +
    # accounts (it is built from them); assembly waits for the opener + ride-along prep.
    g.add_edge(["coaching_focus", "accounts"], "opener")
    g.add_edge(["opener", "ride_along"], "assemble")
    g.add_edge("assemble", END)
    return g.compile()


# Compiled once — the graph shape is fixed (no per-call rebuild, no autonomous loop).
_GRAPH = _build_graph()


def build_brief(
    ctx: AccessContext,
    data: DataAccess,
    retriever: Retriever,
    llm: LLM,
    *,
    rep_id: str | None = None,
    settings: Settings | None = None,
) -> CoachingBrief:
    """Assemble the full, fully-narrated `CoachingBrief` for a rep (the top-ranked rep by
    default, or an explicit in-scope `rep_id`). Deterministic given the seed + a deterministic
    LLM. Raises `ScopeError` for an out-of-scope `rep_id`."""
    final = _GRAPH.invoke(
        {
            "ctx": ctx,
            "data": data,
            "retriever": retriever,
            "llm": llm,
            "settings": settings or get_settings(),
            "rep_id": rep_id,
        }
    )
    return final["brief"]
