"""M28A report persistence tests. Fully mocked, no database required."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import StatementError

from tests.support.app import create_test_app, TEST_MEMBER
from trendora.api.app import get_research_report_service
from trendora.api.research_report_models import ResearchReportRequest, to_report_response
from trendora.api.report_snapshot import snapshot_fingerprint
from trendora.research.recovery import verify_recovery_receipt
from tests.unit.test_research_reporting import _query, _report_service

PATH = "/api/v1/research/report"
PERSISTED_ID = "00000000-0000-4000-8000-0000000000ff"


def _payload() -> dict:
    payload = _query()
    payload["date_from"] = payload["date_from"].isoformat()
    payload["date_to"] = payload["date_to"].isoformat()
    return payload


class FakeSettings:
    def __init__(self, database_url, signing_key=None):
        self.database_url = database_url
        self.report_recovery_signing_key = signing_key
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

    def flush(self):
        for record in self.added:
            if getattr(record, "id", None) is None:
                record.id = UUID(PERSISTED_ID)

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

    app = create_test_app()
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
        assert record.snapshot_origin == "server_generated"
        assert set(record.report) == {
            "status",
            "research",
            "evidence",
            "interpretation",
            "strategy",
            "ideation",
        }
        assert "persistence" not in record.report
        outcome = body["persistence"]
        assert outcome["status"] == "saved"
        assert outcome["report_id"] == PERSISTED_ID
        assert outcome["snapshot_origin"] == "server_generated"
        assert outcome["recovery_receipt"] is None

    @pytest.mark.parametrize("database_url,error,status", [
        (None, None, "failed"),
        ("postgresql://x", RuntimeError("fictional database failure"), "unknown"),
        ("postgresql://x", None, "saved"),
    ])
    @pytest.mark.parametrize("key", [None, "fictional-recovery-signing-key-only"])
    def test_generation_outcomes_share_original_signed_deadline_outside_snapshot(self, monkeypatch, database_url, error, status, key):
        import trendora.api.app as app_module

        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        request_id = UUID("00000000-0000-4000-8000-000000000099")
        response = to_report_response(_report_service([]).build_report(**_query()))
        for index, reference in enumerate(response.research.references):
            reference.collected_at = now - timedelta(days=index + 1)
        original = app_module._snapshot_projection(response)
        fingerprint = snapshot_fingerprint(original)
        deadline = min(reference.collected_at for reference in response.research.references) + timedelta(days=30)
        session = FakeSession()
        factory = FakeFactory(session, error=error)
        monkeypatch.setattr(app_module, "get_utc_now", lambda: now)
        monkeypatch.setattr(app_module, "uuid4", lambda: request_id)
        monkeypatch.setattr(app_module, "get_settings", lambda: FakeSettings(database_url, key))
        monkeypatch.setattr(app_module, "get_session_factory", factory)

        outcome = app_module._persist_research_report(
            ResearchReportRequest(**_payload()), response, TEST_MEMBER.user_id,
        )

        assert outcome.status == status
        assert outcome.request_id == str(request_id)
        if key is None:
            assert outcome.recovery_receipt is None
        else:
            assert verify_recovery_receipt(
                outcome.recovery_receipt, actor_id=TEST_MEMBER.user_id, request_id=request_id,
                fingerprint=fingerprint, signing_key=key, now=now,
            ) == deadline
        response.persistence = outcome
        assert app_module._snapshot_projection(response) == original
        assert snapshot_fingerprint(app_module._snapshot_projection(response)) == fingerprint
        if status == "saved":
            assert session.added[0].source_expires_at == deadline
            assert session.added[0].report == original

    def test_initial_save_records_the_authenticated_actor(self, monkeypatch):
        """The committed row must carry the authenticated actor and request key.

        Recovery looks up ``(created_by, save_request_id)``; a NULL actor would
        make a later recovery insert a duplicate instead of acknowledging.
        """
        session = FakeSession()
        factory = FakeFactory(session)
        client = _app_with_persistence(factory, monkeypatch, "postgresql://x")
        response = client.post(PATH, json=_payload())

        assert response.status_code == 200
        record = session.added[0]
        assert record.created_by == TEST_MEMBER.user_id
        assert record.save_request_id is not None
        assert response.json()["persistence"]["request_id"] == str(record.save_request_id)

    def test_persistence_failure_reports_unknown_outcome(self, monkeypatch):
        factory = FakeFactory(error=RuntimeError("db down"))
        client = _app_with_persistence(factory, monkeypatch, "postgresql://x")
        response = client.post(PATH, json=_payload())

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert factory.calls == 1
        assert body["persistence"]["status"] == "unknown"
        assert body["persistence"]["report_id"] is None

    def test_persistence_error_never_exposes_sql_parameters_or_driver_text(self, monkeypatch, caplog):
        marker = "fictional-sensitive-report-marker"
        error = StatementError(
            "fictional-driver-message",
            "INSERT INTO research_reports (report) VALUES (:report)",
            {"report": marker},
            RuntimeError("fictional-driver-message"),
        )
        assert marker in str(error)
        factory = FakeFactory(error=error)
        client = _app_with_persistence(factory, monkeypatch, "postgresql://x")

        with caplog.at_level("WARNING", logger="trendora.api.app"):
            response = client.post(PATH, json=_payload())

        assert response.status_code == 200
        outcome = response.json()["persistence"]
        assert outcome["status"] == "unknown"
        assert outcome["error_code"] == "persistence_uncertain"
        assert outcome["report_id"] is None
        assert UUID(outcome["request_id"])
        for private_text in (marker, "INSERT INTO", "fictional-driver-message"):
            assert private_text not in response.text
            assert private_text not in caplog.text
        records = [record for record in caplog.records if record.name == "trendora.api.app"]
        assert len(records) == 1
        assert records[0].getMessage() == "Failed to persist research report: StatementError"
        assert records[0].exc_info is None

    def test_unconfigured_database_reports_failed_outcome(self, monkeypatch):
        factory = FakeFactory(FakeSession())
        client = _app_with_persistence(factory, monkeypatch, None)
        response = client.post(PATH, json=_payload())

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert factory.calls == 0
        assert body["persistence"]["status"] == "failed"
        assert body["persistence"]["report_id"] is None
        assert body["persistence"]["error_code"] == "persistence_unconfigured"
