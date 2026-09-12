"""M28A report persistence tests. Fully mocked, no database required."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from trendora.api import create_app
from trendora.api.app import get_research_report_service
from tests.unit.test_research_reporting import _query, _report_service

PATH = "/api/v1/research/report"


def _payload() -> dict:
    payload = _query()
    payload["date_from"] = payload["date_from"].isoformat()
    payload["date_to"] = payload["date_to"].isoformat()
    return payload


class FakeSettings:
    def __init__(self, database_url):
        self.database_url = database_url
        self.ai_provider = "p"
        self.ai_model = "m"
        self.ai_endpoint_url = "https://provider.test/v1/chat/completions"
        self.ai_api_key = "test-key"
        self.youtube_api_key = "yt-key"
        self.meta_access_token = None
        self.meta_graph_api_version = None


class FakeSession:
    def __init__(self):
        self.added = []
        self.committed = False
        self.closed = False

    def add(self, record):
        self.added.append(record)

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


class FakeFactory:
    def __init__(self, session=None, error=None):
        self.session = session
        self.error = error
        self.calls = 0

    def __call__(self):
        # Mirrors get_session_factory(): returns a factory whose call yields a session.
        self.calls += 1
        if self.error is not None:
            raise self.error
        return lambda: self.session


def _app_with_persistence(factory, monkeypatch, database_url):
    import trendora.api.app as app_module

    app = create_app()
    app.dependency_overrides[get_research_report_service] = lambda: _report_service([])
    monkeypatch.setattr(app_module, "get_settings", lambda: FakeSettings(database_url))
    monkeypatch.setattr(app_module, "get_session_factory", factory)
    return TestClient(app)


class TestReportPersistence:
    def test_successful_report_persists_one_insert(self, monkeypatch):
        session = FakeSession()
        factory = FakeFactory(session)
        client = _app_with_persistence(factory, monkeypatch, "postgresql://x")
        response = client.post(PATH, json=_payload())

        assert response.status_code == 200
        body = response.json()
        assert factory.calls == 1
        assert len(session.added) == 1
        record = session.added[0]
        assert session.committed is True
        assert session.closed is True
        assert record.status == body["status"]
        assert record.topic == body["research"]["query"]["topic"]
        assert record.markets == body["research"]["query"]["markets"]
        assert record.source_codes == body["research"]["query"]["sources"]
        assert record.date_from.isoformat() == body["research"]["query"]["date_from"]
        assert record.date_to.isoformat() == body["research"]["query"]["date_to"]
        assert record.report == body

    def test_persistence_failure_does_not_affect_response(self, monkeypatch):
        factory = FakeFactory(error=RuntimeError("db down"))
        client = _app_with_persistence(factory, monkeypatch, "postgresql://x")
        response = client.post(PATH, json=_payload())

        assert response.status_code == 200
        assert response.json()["status"] == "completed"
        assert factory.calls == 1

    def test_unconfigured_database_skips_persistence(self, monkeypatch):
        factory = FakeFactory(FakeSession())
        client = _app_with_persistence(factory, monkeypatch, None)
        response = client.post(PATH, json=_payload())

        assert response.status_code == 200
        assert response.json()["status"] == "completed"
        assert factory.calls == 0
