"""P10-T5 / Step 10b — voice-captured CLOSE drafting (the DM's words, organized — never invented).

Flow: a post-ride voice recording -> text (the `Transcriber` seam, Amazon Transcribe in prod) ->
a DRAFT `CloseRecord` that Claude STRUCTURES from the DM's own words. The draft is REVIEWABLE: it
is returned, not saved — the DM confirms/edits, then saving goes through the EXISTING Step 10a
write path (`DataAccess.save_close_record`), which re-enforces writer-scope RBAC and PRP on
readback. This module never writes; it produces a draft.

NO INVENTION (Principle I/II, FR-011):
- `observations` is the DM's **verbatim transcript** — the LLM never rewrites it, so the core
  record can never contain words the DM did not say.
- The LLM only EXTRACTS the `agreed_actions` / `observe_next` the DM actually stated, as lists.
  The prompt forbids inventing; a category not mentioned yields an empty list; an unparseable or
  non-list LLM response yields empty lists (a fallback that structures nothing rather than
  fabricate). The LLM organizes the DM's words; it decides nothing and takes no action.
"""

from __future__ import annotations

import json

from coach.llm.client import LLM
from coach.llm.transcribe import Transcriber
from coach.schemas import CloseRecord

_STRUCTURE_INSTRUCTION = (
    "You are ORGANIZING a district manager's own post-ride coaching notes — not writing new ones. "
    "From the transcript, extract ONLY the agreed actions and the what-to-observe-next items that "
    "the DM actually stated. Return STRICT JSON of the form "
    '{"agreed_actions": ["..."], "observe_next": ["..."]}. Do NOT invent, infer, or add anything '
    "the DM did not say; if a category was not mentioned, return an empty list for it. Do not "
    "summarize, reword, or change the DM's observations."
)


def _string_list(value: object) -> list[str]:
    """Coerce an LLM-returned field to a clean list of non-empty strings (anything else -> [])."""
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _extract(transcript: str, llm: LLM) -> tuple[list[str], list[str]]:
    """Ask the LLM to extract the agreed-actions / observe-next the DM stated. On any parse failure
    return empty lists — structure nothing rather than fabricate."""
    raw = llm.narrate({"transcript": transcript}, _STRUCTURE_INSTRUCTION).strip()
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return [], []
    if not isinstance(data, dict):
        return [], []
    return _string_list(data.get("agreed_actions")), _string_list(data.get("observe_next"))


def draft_close_record(
    transcript: str,
    llm: LLM,
    *,
    rep_id: str,
    date: str,
    account_id: str | None = None,
) -> CloseRecord:
    """Build a DRAFT `CloseRecord` from a transcript. `observations` is the DM's verbatim words
    (never altered); the LLM only extracts the agreed-actions / observe-next the DM stated. The
    draft is returned for the DM to review/edit — it is NOT saved here. Raises a validation error
    on an empty transcript (an empty recording is not a valid note)."""
    observations = transcript.strip()
    agreed_actions, observe_next = _extract(observations, llm)
    return CloseRecord(
        rep_id=rep_id,
        date=date,
        observations=observations,  # verbatim — the DM's own words, never invented
        agreed_actions=agreed_actions,
        observe_next=observe_next,
        account_id=account_id,
    )


def draft_close_record_from_voice(
    transcriber: Transcriber,
    audio: bytes,
    llm: LLM,
    *,
    rep_id: str,
    date: str,
    account_id: str | None = None,
) -> CloseRecord:
    """Voice -> a reviewable DRAFT `CloseRecord`. Transcribes the recording (the `Transcriber`
    seam; Amazon Transcribe in prod, a fake in tests — no live AWS), then structures the DM's words
    via `draft_close_record`. Returns the draft for review; saving goes through the existing Step
    10a write path (`save_close_record`, writer-scope RBAC + PRP on readback)."""
    transcript = transcriber.transcribe(audio)
    return draft_close_record(transcript, llm, rep_id=rep_id, date=date, account_id=account_id)
