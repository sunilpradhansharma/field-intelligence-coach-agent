"""T040 / F3 — audit records + privacy-in-logging (FR-016).

The constitution treats rep data as HR-sensitive and HCP/prescriber data as private. This
asserts the request path:
- emits exactly ONE privacy-safe audit record per brief generation (and one per reps list);
- logs ONLY allow-listed safe identifiers/metadata (`SAFE_AUDIT_FIELDS`) — never names,
  metrics, or raw PII;
- the audit builder REFUSES (raises) any HR-sensitive / private field by construction.
"""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from coach.api.app import AppDeps, create_app
from coach.config.settings import get_settings
from coach.data_access.interface import AccessContext
from coach.data_access.sqlite_store import SqliteStore
from coach.llm.embeddings import FakeEmbeddings
from coach.observability import audit
from coach.schemas import Role
from coach.synthetic import generate

SEED = 42
DM = {"X-User-Id": "dm_d1"}


class FakeLLM:
    def narrate(self, reason_input: dict, instruction: str) -> str:
        return "Narrated wording for this section."


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "coach.db"
    store = SqliteStore(str(p))
    store.write_dataset(generate(SEED))
    store.close()
    return str(p)


@pytest.fixture
def client(db_path):
    deps = AppDeps(
        db_path=db_path, settings=get_settings(), llm=FakeLLM(), embedder=FakeEmbeddings()
    )
    return TestClient(create_app(deps), raise_server_exceptions=False)


def _audit_records(caplog) -> list[dict]:
    return [
        json.loads(rec.getMessage())
        for rec in caplog.records
        if rec.name == audit.AUDIT_LOGGER_NAME
    ]


def test_brief_emits_one_privacy_safe_audit_record(client, caplog):
    with caplog.at_level(logging.INFO, logger=audit.AUDIT_LOGGER_NAME):
        r = client.get("/api/brief/rep_d1_001", headers=DM)
    assert r.status_code == 200
    records = _audit_records(caplog)
    assert len(records) == 1
    rec = records[0]
    assert rec["event"] == "generate_brief"
    assert rec["user_id"] == "dm_d1"
    assert rec["selected_rep_id"] == "rep_d1_001"
    # ONLY allow-listed safe fields were logged (no name / metric / PII could be present).
    assert set(rec.keys()) <= audit.SAFE_AUDIT_FIELDS


def test_reps_emits_one_privacy_safe_audit_record(client, caplog):
    with caplog.at_level(logging.INFO, logger=audit.AUDIT_LOGGER_NAME):
        r = client.get("/api/reps", headers=DM)
    assert r.status_code == 200
    records = _audit_records(caplog)
    assert len(records) == 1
    assert records[0]["event"] == "list_reps"
    assert set(records[0].keys()) <= audit.SAFE_AUDIT_FIELDS


def test_logs_never_contain_hr_sensitive_or_private_fields(client, caplog):
    ds = generate(SEED)
    rep = next(r for r in ds.reps if r.rep_id == "rep_d1_001")
    account_names = [a.name for a in ds.accounts if a.rep_id == "rep_d1_001"]
    assert account_names  # guard

    with caplog.at_level(logging.DEBUG):  # capture EVERY logger during the request
        r = client.get("/api/brief/rep_d1_001", headers=DM)
    assert r.status_code == 200

    text = caplog.text
    # HR-sensitive rep field (name) never logged.
    assert rep.name not in text
    # Private HCP fields (prescriber/account names) never logged.
    for name in account_names:
        assert name not in text


def test_audit_builder_refuses_hr_sensitive_field():
    ctx = AccessContext(
        user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
    )
    # `name` is HR-sensitive (rep) / private (HCP) — the builder must refuse it.
    with pytest.raises(ValueError):
        audit.build_audit_record("generate_brief", ctx, name="Rep D1-01")
    # A safe metadata field is accepted.
    rec = audit.build_audit_record("generate_brief", ctx, selected_rep_id="rep_d1_001")
    assert rec["selected_rep_id"] == "rep_d1_001"
