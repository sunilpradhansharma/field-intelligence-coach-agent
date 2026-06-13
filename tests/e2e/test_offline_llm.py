"""The server must run FULLY OFFLINE by default — no BEDROCK_MODEL_ID, no AWS, no error.

`make_llm` / `make_embedder` (coach.llm.factory) are the single place that decides real-vs-offline:
real Bedrock IFF the model id is configured, else the deterministic offline provider. These tests
prove the selection logic and that the whole server path (reps list + full brief, both of which
narrate, and the brief also embeds notes) returns 200 with the offline providers — while the
real-Bedrock path is still chosen (and unchanged) when a model id IS configured.
"""

from dataclasses import replace

from fastapi.testclient import TestClient

from coach.api.app import AppDeps, create_app
from coach.config.settings import get_settings
from coach.data_access.sqlite_store import SqliteStore
from coach.llm.client import BedrockLLM
from coach.llm.embeddings import BedrockEmbeddings, FakeEmbeddings
from coach.llm.factory import OfflineLLM, make_embedder, make_llm
from coach.orchestrator.assembly import PENDING_PLACEHOLDERS
from coach.synthetic import generate

SEED = 42
DM = {"X-User-Id": "dm_d1"}


def _offline_settings():
    """A Settings with no Bedrock model ids configured (the local/demo default)."""
    return replace(get_settings(), bedrock_model_id=None, bedrock_embed_model_id=None)


def _configured_settings():
    """A Settings WITH Bedrock model ids (the production case)."""
    return replace(
        get_settings(),
        bedrock_model_id="anthropic.claude-test",
        bedrock_embed_model_id="amazon.titan-embed-test",
        aws_region="us-east-1",
    )


# ----------------------------------------------------------------- factory selection logic
def test_make_llm_is_offline_when_no_model_configured():
    assert isinstance(make_llm(_offline_settings()), OfflineLLM)


def test_make_llm_is_bedrock_when_model_configured():
    # Constructing BedrockLLM only stores the (config) model id — boto3 is lazy, so no AWS call.
    assert isinstance(make_llm(_configured_settings()), BedrockLLM)


def test_make_embedder_is_offline_when_no_model_configured():
    assert isinstance(make_embedder(_offline_settings()), FakeEmbeddings)


def test_make_embedder_is_bedrock_when_model_configured():
    assert isinstance(make_embedder(_configured_settings()), BedrockEmbeddings)


# ------------------------------------------------- the offline narrator covers every section
def test_offline_llm_returns_non_empty_for_every_section_shape():
    llm = OfflineLLM()
    shapes = [
        {"signals": [{"signal": "declining_share", "contribution": 1.0}], "total_score": 5},
        {"focus_area": "Pre-call planning", "signals": [], "data_points": []},
        {"brand": "LILETTA", "context": {"performance": "below"}, "mismatch_flag": True},
        {"talking_points": [{"text": "Share trend in key accounts"}]},
        {"has_history": True, "prior_notes": [{}, {}]},
        {"has_history": False},
        {"theme": "Missed follow-ups", "rep_count": 3, "rep_share": 0.4},
        {
            "district_id": "D1",
            "lift": 2,
            "baseline_position": 4,
            "projected_position": 2,
            "targets": [{}, {}],
        },
        {
            "success_measure": "rising share",
            "insufficient_data": False,
            "variable_findings": [{"variable": "consistent calls"}],
        },
        {"success_measure": "rising share", "insufficient_data": True, "variable_findings": []},
        {},  # unrecognized -> safe non-empty fallback
    ]
    for ri in shapes:
        out = llm.narrate(ri, "any instruction")
        assert out and out.strip(), f"empty narration for {ri}"


# ----------------------------------------------------- the whole server path works offline
def _offline_app(tmp_path):
    p = tmp_path / "coach.db"
    store = SqliteStore(str(p))
    store.write_dataset(generate(SEED))
    store.close()
    s = _offline_settings()
    deps = AppDeps(db_path=str(p), settings=s, llm=make_llm(s), embedder=make_embedder(s))
    return create_app(deps)


def test_get_reps_returns_200_offline(tmp_path):
    client = TestClient(_offline_app(tmp_path), raise_server_exceptions=False)
    r = client.get("/api/reps", headers=DM)
    assert r.status_code == 200
    body = r.json()
    assert body["ranked_reps"]
    # narrate-before-expose still holds with the offline narrator (no placeholder leaks)
    for placeholder in PENDING_PLACEHOLDERS:
        assert placeholder not in r.text


def test_get_full_brief_returns_200_offline(tmp_path):
    # The full brief narrates every section AND embeds notes (the retriever) — both must be offline.
    client = TestClient(_offline_app(tmp_path), raise_server_exceptions=False)
    r = client.get("/api/brief/rep_d1_001", headers=DM)
    assert r.status_code == 200
    for placeholder in PENDING_PLACEHOLDERS:
        assert placeholder not in r.text
