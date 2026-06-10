"""T024 — LLM narration of an ALREADY-COMPUTED `RepRanking` (wording only).

The deterministic ranking (ranks, scores, signal values, contributors) is computed in code
(T023) and is NEVER changed here. This step writes ONLY `reason.summary`, in plain language,
naming the top contributors. Enforced structurally: the output is rebuilt from the input with
just the `summary` field replaced — every other field is preserved by construction
(Principle I/VI, FR-002/FR-012; verified by the anti-LLM-ranking guard test).
"""

from __future__ import annotations

from coach.llm.client import LLM
from coach.schemas import (
    AccountFocus,
    CoachingFocus,
    EmptyState,
    Opener,
    RepRanking,
    RideAlongPrep,
)

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


_RIDE_ALONG_SUMMARY_INSTRUCTION = (
    "Write a short, plain-language summary of this rep's prior coaching: the recent notes, "
    "agreed actions, and what to observe next. Use ONLY the facts provided — do not invent "
    "notes or actions. If there is no history, say so plainly. One or two sentences."
)
_RIDE_ALONG_OPENING_INSTRUCTION = (
    "Suggest a short, plain-language way for the district manager to OPEN the pre-ride "
    "business conversation, grounded ONLY in the prior coaching facts provided. Do not invent "
    "anything. One sentence."
)


def _ride_along_input(prep: RideAlongPrep | EmptyState) -> dict:
    """Read-only facts handed to the LLM. It may phrase them; it may not alter them."""
    if isinstance(prep, EmptyState):
        return {"rep_id": prep.rep_id, "has_history": False, "message": prep.message}
    return {
        "rep_id": prep.rep_id,
        "has_history": prep.has_history,
        "prior_notes": [n.model_dump() for n in prep.prior_notes],
        "agreed_actions": [a.model_dump() for a in prep.agreed_actions],
        "observe_next": [o.model_dump() for o in prep.observe_next],
    }


def narrate_ride_along(prep: RideAlongPrep | EmptyState, llm: LLM) -> RideAlongPrep | EmptyState:
    """Return a copy of `prep` with ONLY the wording fields written by the LLM —
    `reason.summary` (both types) and `opening` (RideAlongPrep). The facts (notes, agreed
    actions, observe-next, provenance, empty-state message) are preserved by construction
    (FR-006; verified by the anti-LLM guard test)."""
    facts = _ride_along_input(prep)
    summary = llm.narrate(facts, _RIDE_ALONG_SUMMARY_INSTRUCTION).strip() or prep.reason.summary
    new_reason = prep.reason.model_copy(update={"summary": summary})
    if isinstance(prep, EmptyState):
        return prep.model_copy(update={"reason": new_reason})
    opening = llm.narrate(facts, _RIDE_ALONG_OPENING_INSTRUCTION).strip() or prep.opening
    return prep.model_copy(update={"reason": new_reason, "opening": opening})


_ACCOUNT_INSTRUCTION = (
    "Write a short, plain-language reason a district manager will read about this key account "
    "and brand. Use ONLY the structured business context and data points provided — name the "
    "brand and the key numbers, do not invent anything, and do not change the mismatch flag. "
    "One or two sentences."
)


def _account_input(focus: AccountFocus) -> dict:
    """Read-only facts handed to the LLM. It may phrase them; it may not alter them."""
    return {
        "account_id": focus.account_id,
        "brand": focus.brand.value,  # display name (e.g. "LILETTA")
        "context": focus.context.model_dump(),
        "mismatch_flag": focus.mismatch_flag,
        "data_points": [d.model_dump() for d in focus.reason.data_points],
    }


def narrate_account_focus(focus: AccountFocus, llm: LLM) -> AccountFocus:
    """Return a copy of `focus` with ONLY `reason.summary` replaced by LLM prose. The metrics,
    the brand, the mismatch flag, and the data points are preserved by construction (FR-007/008;
    anti-LLM guard verifies it)."""
    summary = llm.narrate(_account_input(focus), _ACCOUNT_INSTRUCTION).strip()
    if not summary:
        summary = focus.reason.summary  # schema requires a non-empty summary; keep prior
    new_reason = focus.reason.model_copy(update={"summary": summary})
    return focus.model_copy(update={"reason": new_reason})


def narrate_account_focuses(focuses: list[AccountFocus], llm: LLM) -> list[AccountFocus]:
    return [narrate_account_focus(f, llm) for f in focuses]


_OPENER_TEXT_INSTRUCTION = (
    "Write a short, natural opening line a district manager can use to start the morning "
    "business conversation with the rep. Rephrase ONLY the talking points provided — do not "
    "add facts, numbers, brands, or recommendations that are not in them. It is a suggestion "
    "the DM may edit, never an instruction or action. One or two sentences."
)
_OPENER_SUMMARY_INSTRUCTION = (
    "In one short sentence, explain what this opener is built from, using ONLY the talking "
    "points and their sources provided. Do not invent anything."
)


def _opener_input(opener: Opener) -> dict:
    """Read-only facts handed to the LLM. It may rephrase them; it may not alter or extend."""
    return {
        "talking_points": [p.model_dump() for p in opener.talking_points],
        "data_points": [d.model_dump() for d in opener.reason.data_points],
    }


def narrate_opener(opener: Opener, llm: LLM) -> Opener:
    """Return a copy of `opener` with ONLY the wording written by the LLM — the opening `text`
    and `reason.summary`. The selected talking points and their provenance are preserved by
    construction (FR-009; verified by the anti-LLM guard), so the LLM cannot add talking
    points or invent facts."""
    facts = _opener_input(opener)
    text = llm.narrate(facts, _OPENER_TEXT_INSTRUCTION).strip() or opener.text
    summary = llm.narrate(facts, _OPENER_SUMMARY_INSTRUCTION).strip() or opener.reason.summary
    new_reason = opener.reason.model_copy(update={"summary": summary})
    return opener.model_copy(update={"text": text, "reason": new_reason})
