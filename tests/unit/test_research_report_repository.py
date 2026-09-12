"""M28B report read endpoint tests. Fully mocked, no database required."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from trendora.api import create_app
from trendora.api.app import get_session

REPORT_ID = "123e4567-e89b-12d3-a456-426614174000"
FULL_SNAPSHOT = {
    "status": "completed",
    "research": {
        "query": {
            "topic": "Test",
            "markets": ["SG"],
            "market": "SG",
            "date_from": "2026-08-01",
            "date_to": "2026-08-31",
            "sources": ["youtube"],
            "result_limit": 6,
            "facebook_page_id": None,
        },
        "coverage": {"completeness": "complete", "sources": []},
        "executed_sources": ["youtube"],
        "status": "completed",
        "references": [],
    },
    "evidence": None,
    "interpretation": None,
    "strategy": None,
    "ideation": None,
}


class FakeRecord:
    def __init__(self, **kwargs):
        self.id = UUID(REPORT_ID)
        self.created_at = datetime(2026, 9, 12, 10, 0, 0)
        self.status = "completed"
        self.topic = "Test topic"
        self.markets = ["SG", "ID"]
        self.source_codes = ["youtube"]
        self.date_from = date(2026, 8, 1)
        self.date_to = date(2026, 8, 31)
        self.report = FULL_SNAPSHOT
        for key, value in kwargs.items():
            setattr(self, key, value)


class _Query:
    def __init__(self, records):
        self._records = records
        self._limit = None

    def order_by(self, *args):
        return self

    def offset(self, offset):
        self._records = self._records[offset:]
        return self

    def limit(self, limit):
        self._limit = limit
        return self

    def all(self):
        if self._limit is None:
            return list(self._records)
        return list(self._records[: self._limit])

    def count(self):
        return len(self._records)

    def filter(self, *args):
        return self

    def first(self):
        return self._records[0] if self._records else None


class FakeSession:
    def __init__(self, records=None):
        self.records = records or []

    def query(self, model):
        return _Query(self.records)


def _app_with_session(session) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


class TestListReports:
    def test_list_returns_metadata_summary(self):
        client = _app_with_session(FakeSession([FakeRecord()]))
        response = client.get("/api/v1/research/reports")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["topic"] == "Test topic"
        assert data[0]["markets"] == ["SG", "ID"]
        assert data[0]["source_codes"] == ["youtube"]
        assert "report" not in data[0]

    def test_list_empty(self):
        client = _app_with_session(FakeSession([]))
        response = client.get("/api/v1/research/reports")
        assert response.status_code == 200
        assert response.json() == []

    def test_invalid_pagination_returns_422(self):
        client = _app_with_session(FakeSession([]))
        assert client.get("/api/v1/research/reports?limit=0").status_code == 422
        assert client.get("/api/v1/research/reports?limit=101").status_code == 422
        assert client.get("/api/v1/research/reports?offset=-1").status_code == 422


class TestFetchReport:
    def test_fetch_returns_full_snapshot(self):
        client = _app_with_session(FakeSession([FakeRecord()]))
        response = client.get(f"/api/v1/research/reports/{REPORT_ID}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert "research" in data
        assert data["research"]["query"]["markets"] == ["SG"]

    def test_404_for_unknown_uuid(self):
        client = _app_with_session(FakeSession([]))
        response = client.get(
            "/api/v1/research/reports/00000000-0000-4000-8000-000000000000"
        )
        assert response.status_code == 404

    def test_404_for_invalid_uuid(self):
        client = _app_with_session(FakeSession([]))
        response = client.get("/api/v1/research/reports/not-a-uuid")
        assert response.status_code == 404
