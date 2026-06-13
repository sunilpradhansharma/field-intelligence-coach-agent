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
from coach.llm.factory import OfflineLLM
from coach.synthetic import generate


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
        llm=OfflineLLM(),  # always offline here — the demo never calls AWS (see coach.llm.factory)
        embedder=FakeEmbeddings(),
    )
    return create_app(deps)


app = create_demo_app()
