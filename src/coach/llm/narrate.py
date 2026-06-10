"""T024 — LLM narration of an ALREADY-COMPUTED `RepRanking` (wording only).

The deterministic ranking (ranks, scores, signal values, contributors) is computed in code
(T023) and is NEVER changed here. This step writes ONLY `reason.summary`, in plain language,
naming the top contributors. Enforced structurally: the output is rebuilt from the input with
just the `summary` field replaced — every other field is preserved by construction
(Principle I/VI, FR-002/FR-012; verified by the anti-LLM-ranking guard test).
"""

from __future__ import annotations

from coach.llm.client import LLM
from coach.schemas import CoachingFocus, RepRanking

_INSTRUCTION = (
    "Write a short, plain-language reason a district manager will read about why this sales "
    "rep needs coaching. Use ONLY the structured signals and data points provided — do not "
    "invent numbers, and do not change any ranking. One or two sentences."
)

_FOCUS_INSTRUCTION = (
    "Write a short, plain-language reason a district manager will read for coaching this rep "
    "on the given focus area. Use ONLY the structured signal and data points provided — do "
    "not invent numbers, and do not change the focus area. One or two sentences."
)


def _reason_input(ranking: RepRanking) -> dict:
    """The structured facts handed to the LLM. It may phrase these; it may not alter them."""
    r = ranking.reason
    return {
        "rep_id": ranking.rep_id,
        "rank": ranking.rank,
        "total_score": ranking.total_score,
        "signals": [s.model_dump() for s in r.signals],
        "top_contributors": [d.model_dump() for d in r.data_points],
    }


def narrate_ranking(ranking: RepRanking, llm: LLM) -> RepRanking:
    """Return a copy of `ranking` with ONLY `reason.summary` replaced by LLM prose."""
    summary = llm.narrate(_reason_input(ranking), _INSTRUCTION).strip()
    if not summary:
        summary = ranking.reason.summary  # schema requires a non-empty summary; keep prior
    new_reason = ranking.reason.model_copy(update={"summary": summary})
    return ranking.model_copy(update={"reason": new_reason})


def narrate_rankings(rankings: list[RepRanking], llm: LLM) -> list[RepRanking]:
    return [narrate_ranking(r, llm) for r in rankings]


def _focus_input(focus: CoachingFocus) -> dict:
    """Structured facts handed to the LLM for a coaching focus. It may phrase; not alter."""
    r = focus.reason
    return {
        "focus_area": focus.focus_area,
        "signals": [s.model_dump() for s in r.signals],
        "data_points": [d.model_dump() for d in r.data_points],
    }


def narrate_focus(focus: CoachingFocus, llm: LLM) -> CoachingFocus:
    """Return a copy of `focus` with ONLY `reason.summary` replaced by LLM prose.

    The deterministic component already DECIDED the focus area and its reason structure
    (T027); this step is wording only. Rebuilt via `model_copy` so the `focus_area`, signals,
    and data points are preserved by construction (FR-005; anti-LLM guard verifies it)."""
    summary = llm.narrate(_focus_input(focus), _FOCUS_INSTRUCTION).strip()
    if not summary:
        summary = focus.reason.summary  # schema requires a non-empty summary; keep prior
    new_reason = focus.reason.model_copy(update={"summary": summary})
    return focus.model_copy(update={"reason": new_reason})


def narrate_focuses(focuses: list[CoachingFocus], llm: LLM) -> list[CoachingFocus]:
    return [narrate_focus(f, llm) for f in focuses]
