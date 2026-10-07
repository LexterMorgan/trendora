"""Gate A: rolling 30-day report visibility: cutoff math and route wiring."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.support.app import ADMIN_MEMBER, TEST_MEMBER, create_test_app
from trendora.api.app import get_session, get_utc_now
from trendora.api.auth import report_visible_from

FROZEN = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)
CUTOFF = FROZEN - timedelta(days=30)
REPORT_PATH = "/api/v1/research/reports"


def _client(monkeypatch, member=None) -> TestClient:
    app = create_test_app(member)
    app.dependency_overrides[get_utc_now] = lambda: FROZEN
    app.dependency_overrides[get_session] = lambda: object()
    return TestClient(app)


def _patch_list(monkeypatch) -> dict:
    captured: dict = {}

    def fake(session, *, limit=50, offset=0, visible_from=None):
        captured.update(limit=limit, offset=offset, visible_from=visible_from)
        return [], 0

    monkeypatch.setattr("trendora.research.repository.get_report_records", fake)
    return captured


def _patch_direct(monkeypatch) -> dict:
    captured: dict = {}

    def fake(session, report_id, *, visible_from=None):
        captured.update(report_id=report_id, visible_from=visible_from)
        return None

    monkeypatch.setattr(
        "trendora.research.repository.get_report_record_by_id", fake
    )
    return captured


class TestCutoffMath:
    def test_member_cutoff_is_exactly_30_days(self) -> None:
        assert report_visible_from(TEST_MEMBER, FROZEN) == CUTOFF

    def test_admin_gets_full_history(self) -> None:
        assert report_visible_from(ADMIN_MEMBER, FROZEN) is None

    def test_can_approve_is_not_full_history(self) -> None:
        approver = replace(TEST_MEMBER, can_approve=True)
        assert report_visible_from(approver, FROZEN) == CUTOFF


class TestListRouteWiring:
    def test_member_list_passes_cutoff(self, monkeypatch) -> None:
        captured = _patch_list(monkeypatch)
        response = _client(monkeypatch).get(f"{REPORT_PATH}?limit=5&offset=3")
        assert response.status_code == 200
        assert captured == {"limit": 5, "offset": 3, "visible_from": CUTOFF}

    def test_admin_list_passes_none(self, monkeypatch) -> None:
        captured = _patch_list(monkeypatch)
        response = _client(monkeypatch, ADMIN_MEMBER).get(REPORT_PATH)
        assert response.status_code == 200
        assert captured["visible_from"] is None

    def test_member_direct_report_passes_cutoff(self, monkeypatch) -> None:
        captured = _patch_direct(monkeypatch)
        response = _client(monkeypatch).get(f"{REPORT_PATH}/{uuid4()}")
        assert response.status_code == 404
        assert captured["visible_from"] == CUTOFF

    def test_admin_direct_report_passes_none(self, monkeypatch) -> None:
        captured = _patch_direct(monkeypatch)
        response = _client(monkeypatch, ADMIN_MEMBER).get(f"{REPORT_PATH}/{uuid4()}")
        assert response.status_code == 404
        assert captured["visible_from"] is None
