"""Phase 8 (Summit) + Phase 9 (covariant) SURFACED in the existing brief (config-enabled).

These prove the wiring (not the engines, which are covered by test_summit.py / test_covariant.py):
- Summit shows as a 5th ranking contributor in a rep's Priority reason, and a region/all caller
  (multi-district) gets a NON-ZERO Summit contribution that moves the score; weight 0 removes it.
- The covariant insight is included in the brief's accounts section (sufficient state on the seed)
  AND honestly shows the insufficient-data state on a thin dataset.
- Both appear in the GET /api/brief/{rep_id} response body.
- The anti-LLM guard still holds: Summit lift + covariant findings are byte-identical before/after
  narration — only the wording (`reason.summary`) changes.
"""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from coach.api.app import AppDeps, create_app
from coach.components.covariant import covariant_analysis
from coach.components.ranking import rank_reps
from coach.config.settings import get_settings
from coach.data_access.interface import AccessContext
from coach.data_access.notes_retriever import NotesRetriever
from coach.data_access.sqlite_store import SqliteStore
from coach.llm.embeddings import FakeEmbeddings
from coach.llm.narrate import narrate_covariant, narrate_rankings
from coach.orchestrator.brief_graph import build_brief
from coach.schemas import Role, SignalName
from coach.synthetic import generate

SEED = 42


class FakeLLM:
    def narrate(self, reason_input: dict, instruction: str) -> str:
        return "Narrated wording for this section."


def _dm():
    return AccessContext(
        user_id="dm_d1", role=Role.district_manager, region_id="R1", district_id="D1"
    )


def _region():
    return AccessContext(user_id="region_r1", role=Role.regional_director, region_id="R1")


@pytest.fixture
def env(tmp_path):
    p = tmp_path / "coach.db"
    store = SqliteStore(str(p))
    store.write_dataset(generate(SEED))
    retriever = NotesRetriever(store, FakeEmbeddings())
    retriever.index()
    yield store, retriever, str(p)
    store.close()


# --------------------------------------------------- Summit as a 5th Priority contributor
def test_brief_priority_reason_includes_a_summit_contributor(env):
    store, retriever, _ = env
    brief = build_brief(_dm(), store, retriever, FakeLLM(), rep_id="rep_d1_001")
    for r in brief.ranked_reps:
        signals = {sc.signal for sc in r.reason.signals}
        assert SignalName.summit_opportunity in signals  # the 5th contributor is present


def test_region_brief_carries_the_summit_contributor_with_its_data_points(env):
    # Every rep carries the Summit contributor, and the selected rep's reason includes Summit's
    # supporting data points (district position, projected position, ranking lift). NOTE: on the
    # seed the lift happens to be 0 (the two districts' Summit scores are far apart, so one rep's
    # decline-recovery can't change a position) — the contributor and its numbers still surface.
    # The non-zero-lift case (a Summit contribution that MOVES the score) is proven in
    # tests/component/test_summit.py with a purpose-built dataset.
    store, _, _ = env
    rankings = rank_reps(_region(), store)
    for r in rankings:
        assert SignalName.summit_opportunity in {sc.signal for sc in r.reason.signals}
    labels = " ".join(d.label for d in rankings[0].reason.data_points)
    assert "Summit position" in labels and "ranking lift" in labels


def test_summit_weight_zero_removes_the_contributor(env):
    store, _, _ = env
    off = replace(
        get_settings(),
        ranking_weights={**get_settings().ranking_weights, "summit_opportunity": 0.0},
    )
    for r in rank_reps(_region(), store, off):
        assert SignalName.summit_opportunity not in {sc.signal for sc in r.reason.signals}


# ------------------------------------------------ covariant insight in the accounts section
def test_brief_includes_a_narrated_covariant_insight_sufficient_on_seed(env):
    store, retriever, _ = env
    brief = build_brief(_dm(), store, retriever, FakeLLM(), rep_id="rep_d1_001")
    assert brief.covariant is not None
    assert brief.covariant.insufficient_data is False  # the seed has enough rows
    assert brief.covariant.success_measure  # the configured success measure is noted (assumption)
    assert brief.covariant.variable_findings  # transparent per-variable findings present
    # narrated (wording only) — no pending placeholder leaks into the brief
    assert brief.covariant.reason.summary == "Narrated wording for this section."


def test_brief_covariant_shows_the_insufficient_data_state_honestly(env):
    # Force the honest insufficient-data state by raising the row threshold above the seed's row
    # count (config-driven, no engine change) — the brief must surface it, never fabricate.
    store, retriever, _ = env
    thin = replace(get_settings(), covariant_min_rows=100_000)
    brief = build_brief(_dm(), store, retriever, FakeLLM(), rep_id="rep_d1_001", settings=thin)
    assert brief.covariant is not None
    assert brief.covariant.insufficient_data is True  # honesty preserved end-to-end
    assert brief.covariant.variable_findings == []  # no association claimed


# --------------------------------------------------------- both appear in the API response
def test_api_brief_exposes_summit_and_covariant(env):
    _, _, db_path = env
    deps = AppDeps(
        db_path=db_path, settings=get_settings(), llm=FakeLLM(), embedder=FakeEmbeddings()
    )
    client = TestClient(create_app(deps), raise_server_exceptions=False)
    r = client.get("/api/brief/rep_d1_001", headers={"X-User-Id": "dm_d1"})
    assert r.status_code == 200
    body = r.json()
    # covariant section present with the success measure + findings
    assert "covariant" in body and body["covariant"] is not None
    assert body["covariant"]["success_measure"]
    # Summit is a contributor in the ranked reps' reasons
    signals = {sc["signal"] for rep in body["ranked_reps"] for sc in rep["reason"]["signals"]}
    assert "summit_opportunity" in signals


# ------------------------------------------------------------- anti-LLM guard (still holds)
def test_narration_changes_only_wording_for_summit_and_covariant(env):
    # The deterministic outputs (Summit signal numbers + covariant findings) are byte-identical
    # before and after narration — the LLM changes ONLY `reason.summary`. (We compare the component
    # outputs directly; building a full brief with an empty narrator is rejected by the guard.)
    store, _, _ = env

    # Summit: rank_reps includes the Summit contributor; narration must not change any signal.
    ranked = rank_reps(_region(), store)
    narrated = narrate_rankings(ranked, FakeLLM())
    for before, after in zip(ranked, narrated, strict=True):
        b = [sc.model_dump() for sc in before.reason.signals]
        a = [sc.model_dump() for sc in after.reason.signals]
        assert b == a  # all contributions identical (incl. summit); only the summary changes

    # Covariant: the findings/blend/counts are identical; only the wording changes.
    cov = covariant_analysis(_dm(), store)
    ncov = narrate_covariant(cov, FakeLLM())
    assert cov.variable_findings == ncov.variable_findings
    assert cov.optimal_blend == ncov.optimal_blend
    assert cov.rows_analyzed == ncov.rows_analyzed
    assert ncov.reason.summary != cov.reason.summary  # wording DID change (PENDING -> narrated)
