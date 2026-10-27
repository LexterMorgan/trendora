"""On-demand content generation from saved reports (offline)."""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from tests.support.app import create_test_app
from tests.unit.test_research_reporting import _query, _report_service
from trendora.api.app import _persist_research_report
from trendora.api.report_snapshot import SNAPSHOT_FIELDS
from trendora.api.research_report_models import (
    PersistenceOutcomeResponse,
    to_report_response,
)
from trendora.api.report_content import build_content_context
from trendora.config import reset_settings_cache
from trendora.research.reporting import ResearchReportService

PATH = "/api/v1/research/reports/source-id/content"


@pytest.fixture(autouse=True)
def _ai_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the content route's provider configuration deterministic.

    The route builds its AI clients from settings, so without these values the
    endpoint answers 503 and the test would only pass on a machine with a real
    ``.env``. No request is made: generation itself is monkeypatched.
    """
    for key, value in {
        "TRENDORA_AI_PROVIDER": "openai-compatible",
        "TRENDORA_AI_MODEL": "test-model",
        "TRENDORA_AI_ENDPOINT_URL": "https://example.test/v1/chat/completions",
        "TRENDORA_AI_API_KEY": "test-key",
    }.items():
        monkeypatch.setenv(key, value)
    reset_settings_cache()
    yield
    reset_settings_cache()


def _source_snapshot():
    report = _report_service([]).build_report(**_query(), include_content_tools=False)
    return to_report_response(report).model_dump(mode="json", include=set(SNAPSHOT_FIELDS))


def _client(monkeypatch, snapshot, *, captured=None):
    record = {
        "id": "source-id",
        "created_at": "2026-10-27T00:00:00+00:00",
        "status": "research_completed",
        "topic": snapshot["research"]["query"]["topic"],
        "markets": snapshot["research"]["query"]["markets"],
        "source_codes": snapshot["research"]["query"]["sources"],
        "date_from": snapshot["research"]["query"]["date_from"],
        "date_to": snapshot["research"]["query"]["date_to"],
        "snapshot_origin": "server_generated",
        "source_expires_at": None,
        "report": copy.deepcopy(snapshot),
    }
    monkeypatch.setattr(
        "trendora.research.repository.get_report_record_by_id",
        lambda *args, **kwargs: record,
    )
    monkeypatch.setattr(
        "trendora.api.app._persist_research_report",
        lambda payload, response, actor_id: (
            captured.append(copy.deepcopy(response.model_dump(mode="json")))
            if captured is not None else None
        ) or PersistenceOutcomeResponse(
            status="saved",
            request_id=None,
            report_id="new-id",
            snapshot_origin="server_generated",
            error_code=None,
        ),
    )
    app = create_test_app()
    return TestClient(app), record


def test_content_endpoint_appends_completed_snapshot_without_mutating_source(monkeypatch):
    snapshot = _source_snapshot()
    original = copy.deepcopy(snapshot)
    captured = []
    client, record = _client(monkeypatch, snapshot, captured=captured)

    content_service = _report_service([])
    pack, interpretation = build_content_context(snapshot)
    strategy, ideation = content_service.generate_content(pack, interpretation)
    monkeypatch.setattr(
        ResearchReportService,
        "generate_content",
        lambda self, pack, interpretation, deadline=None: (strategy, ideation),
    )

    response = client.post(PATH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["strategy"] is not None
    assert body["ideation"] is not None
    assert body["persistence"]["report_id"] == "new-id"
    assert record["report"] == original
    assert len(captured) == 1
    assert captured[0]["status"] == "completed"
    assert captured[0]["strategy"] is not None


def test_content_endpoint_rejects_no_evidence_report(monkeypatch):
    snapshot = _source_snapshot()
    snapshot["status"] = "no_evidence"
    snapshot["evidence"] = None
    snapshot["interpretation"] = None
    client, _ = _client(monkeypatch, snapshot)
    response = client.post(PATH)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "content_not_available"


def test_content_endpoint_rejects_expired_report(monkeypatch):
    snapshot = _source_snapshot()
    client, record = _client(monkeypatch, snapshot)
    record["status"] = "source_data_expired"
    response = client.post(PATH)
    assert response.status_code == 410
