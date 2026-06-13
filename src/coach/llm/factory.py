"""The ONE place that decides which LLM / embeddings provider the app narrates and retrieves with.

Rule: use the real Amazon Bedrock provider IFF its model id is configured (`BEDROCK_MODEL_ID` /
`BEDROCK_EMBED_MODEL_ID`, read from `Settings` — never hard-coded); otherwise fall back to the
DETERMINISTIC OFFLINE provider so a local/demo run works with NO AWS call and no error. This is a
safe offline *fallback* — it does not bypass config for the real path (the real model id still
comes only from config). The API, the orchestrator, and the UI all build their providers here, so
no caller can construct a bare `BedrockLLM()` that crashes offline.

The offline narrator writes WORDING ONLY — it phrases the already-computed structured `reason`
into one short sentence; it adds no facts, changes no numbers, and makes no network call
(Principle I/VI). Synthetic/offline-safe by construction.
"""

from __future__ import annotations

from coach.config.settings import Settings, get_settings
from coach.llm.client import LLM, BedrockLLM
from coach.llm.embeddings import BedrockEmbeddings, EmbeddingProvider, FakeEmbeddings
from coach.llm.narrate import offline_ranking_summary


class OfflineLLM:
    """Deterministic, offline stand-in for the Bedrock LLM (local/demo + the offline fallback).

    Wording only: it turns the structured `reason_input` for any brief section into one short,
    readable sentence using ONLY the facts it is given — it never ranks, scores, or invents data,
    and never calls AWS. Same input -> same text. Covers every section the app narrates (rep
    ranking, coaching focus, accounts, opener, ride-along, and the leadership theme / Summit /
    covariant sections); an unrecognized shape still gets a safe, non-empty line so the
    narrate-before-expose guard is always satisfied."""

    def narrate(self, reason_input: dict, instruction: str) -> str:
        ri = reason_input
        # Coaching focus
        if "focus_area" in ri:
            return f"Coach on {ri['focus_area'].lower()} — the rep's recent signals point here."
        # Account / brand
        if "brand" in ri:
            ctx = ri.get("context", {})
            tail = (
                "call activity is dropping where the opportunity is biggest"
                if ri.get("mismatch_flag")
                else f"{ctx.get('performance', 'tracked')} performance, worth a steady look"
            )
            return f"{ri['brand']}: {tail}."
        # Opener (talking points present)
        if "talking_points" in ri:
            pts = ri.get("talking_points", [])
            if "OPEN" in instruction.upper():
                lead = pts[0]["text"] if pts else "today's priorities"
                return f"Let's start with {lead.lower()} — how are you thinking about it?"
            return "Built from the rep's top priority signal, coaching focus, and a key account."
        # Ride-along prep / empty state
        if "has_history" in ri:
            if not ri.get("has_history"):
                return "No prior coaching history yet for this rep — start fresh today."
            n = len(ri.get("prior_notes", []))
            if "OPEN" in instruction.upper():
                return "Pick up on the actions you agreed last time and what you said you'd watch."
            return f"Recent coaching covered {n} prior note(s), with agreed actions to follow up."
        # Leadership theme (counts/shares only — never an individual)
        if "theme" in ri:
            n = ri.get("rep_count")
            share = ri.get("rep_share")
            pct = (
                f"{round(share * 100)}% of the team"
                if isinstance(share, int | float)
                else "the team"
            )
            return (
                f"Team pattern — {ri['theme']}: seen across {n} rep(s) ({pct}); "
                "a coaching theme to address at the team level, not an individual."
            )
        # Summit ranking optimization
        if "district_id" in ri and "lift" in ri:
            base, proj = ri.get("baseline_position"), ri.get("projected_position")
            move = f"from #{base} to #{proj}" if base is not None and proj is not None else "upward"
            tcount = len(ri.get("targets", []))
            return (
                f"Focusing the top {tcount} target account(s) could move the district's Summit "
                f"position {move} (lift {ri.get('lift')})."
            )
        # Covariant analysis
        if "success_measure" in ri:
            if ri.get("insufficient_data"):
                return (
                    "Not enough data yet to draw a reliable covariant pattern — directional only."
                )
            findings = ri.get("variable_findings", [])
            top = (
                (findings[0].get("variable") or findings[0].get("name") or "the tracked behaviors")
                if findings
                else "the tracked behaviors"
            )
            return f"Reps who do {top} tend to align with success ({ri['success_measure']})."
        # Rep ranking (signals present) — priority-aware, config-driven (no-gap reps are not
        # called "the priority"); deterministic. See coach.llm.narrate.offline_ranking_summary.
        if "signals" in ri:
            return offline_ranking_summary(ri)
        return "See the supporting signals and data points below."


def make_llm(settings: Settings | None = None) -> LLM:
    """Return the LLM to narrate with: real Bedrock IFF `bedrock_model_id` is configured (model id
    from config — unchanged production path), else the deterministic `OfflineLLM` so local/demo
    runs work with no AWS and no error."""
    settings = settings or get_settings()
    if settings.bedrock_model_id:
        # Thread the SAME settings through (don't let BedrockLLM re-read a different global).
        return BedrockLLM(model_id=settings.bedrock_model_id, region=settings.aws_region)
    return OfflineLLM()


def make_embedder(settings: Settings | None = None) -> EmbeddingProvider:
    """Return the embeddings provider for the notes retriever: real Bedrock Titan IFF
    `bedrock_embed_model_id` is configured, else deterministic offline `FakeEmbeddings` so the
    full-brief path (which embeds notes) also runs offline with no AWS."""
    settings = settings or get_settings()
    if settings.bedrock_embed_model_id:
        return BedrockEmbeddings(
            model_id=settings.bedrock_embed_model_id, region=settings.aws_region
        )
    return FakeEmbeddings()
