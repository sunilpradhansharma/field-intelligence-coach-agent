"""Offline demo server for the read-only brief UI (T039) — run the whole thing with no AWS.

`uvicorn coach.api.demo:app` serves the same read-only app as `coach.api.app`, but wired with
a DETERMINISTIC offline narrator + offline embeddings and an auto-seeded synthetic dataset, so
the page renders end-to-end with **no live Bedrock call**. The production entrypoint
(`coach.api.app:app`) uses real Bedrock (model id from config).

The demo narrator only writes wording (it never ranks, scores, or invents data) — it phrases the
already-computed structured `reason` into a short readable sentence, exactly like the real LLM
seam. Synthetic data only (Principle III).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from coach.api.app import AppDeps, create_app
from coach.config.settings import get_settings
from coach.data_access.sqlite_store import SqliteStore
from coach.llm.embeddings import FakeEmbeddings
from coach.llm.narrate import offline_ranking_summary
from coach.synthetic import generate


class DemoNarrator:
    """Deterministic, offline stand-in for the Bedrock LLM. Wording only — turns the structured
    reason input into one short sentence; adds no facts and changes no numbers."""

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
        # Rep ranking (signals present) — priority-aware wording, config-driven (no-gap reps are
        # not called "the priority"); deterministic. See coach.llm.narrate.offline_ranking_summary.
        if "signals" in ri:
            return offline_ranking_summary(ri)
        return "See the supporting signals and data points below."


def _seeded_db_path() -> str:
    """Generate the synthetic dataset into a temp file once, so each request opens its own
    per-request connection to it (the production data-access pattern)."""
    settings = get_settings()
    db_dir = Path(tempfile.gettempdir()) / "coach-demo"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "coach.db"
    store = SqliteStore(str(db_path))
    store.write_dataset(generate(settings.seed))
    store.close()
    return str(db_path)


def create_demo_app():
    settings = get_settings()
    deps = AppDeps(
        db_path=_seeded_db_path(),
        settings=settings,
        llm=DemoNarrator(),
        embedder=FakeEmbeddings(),
    )
    return create_app(deps)


app = create_demo_app()
