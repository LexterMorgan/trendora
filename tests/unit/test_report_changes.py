"""Finding changes against the nearest older run of the same topic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from copy import deepcopy

import pytest

from fastapi.testclient import TestClient

from tests.support.app import TEST_MEMBER, create_test_app
from trendora.api.app import get_session, get_utc_now

FROZEN = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
CUTOFF = FROZEN - timedelta(days=30)
PATH = "/api/v1/research/reports/{report_id}/changes"


def _record(report_id: str, created_at: datetime, statements: list[str]) -> dict:
    return {
        "id": report_id,
        "created_at": created_at.isoformat(),
        "status": "completed",
        "topic": "Exact topic",
        "markets": [],
        "source_codes": [],
        "date_from": "2026-08-01",
        "date_to": "2026-08-31",
        "snapshot_origin": "server_generated",
        "report": {
            "status": "completed",
            "research": {},
            "interpretation": {
                "interpretations": [
                    {"statement": statement, "citations": []}
                    for statement in statements
                ]
            },
        },
    }


def _client(monkeypatch, base: dict | None, previous: dict | None) -> TestClient:
    captured: dict = {}

    def fake_base(session, report_id, *, visible_from=None, now=None):
        captured["visible_from"] = visible_from
        return base

    def fake_previous(session, *, topic, before_created_at, visible_from=None, now=None):
        captured.update(
            topic=topic,
            before_created_at=before_created_at,
            previous_visible_from=visible_from,
            previous_now=now,
        )
        return previous

    monkeypatch.setattr(
        "trendora.research.repository.get_report_record_by_id", fake_base
    )
    monkeypatch.setattr(
        "trendora.research.repository.get_previous_report_record", fake_previous
    )
    app = create_test_app(TEST_MEMBER)
    app.dependency_overrides[get_session] = lambda: object()
    app.dependency_overrides[get_utc_now] = lambda: FROZEN
    client = TestClient(app)
    client.captured = captured  # type: ignore[attr-defined]
    return client


def test_identical_runs_report_no_new_or_dropped_findings(monkeypatch) -> None:
    base = _record("base", FROZEN, ["A finding.", "B finding."])
    previous = _record("previous", FROZEN - timedelta(days=7), ["A finding.", "B finding."])
    client = _client(monkeypatch, base, previous)

    response = client.get(PATH.format(report_id="base"))

    assert response.status_code == 200
    assert response.json() == {
        "previous_report_id": "previous",
        "previous_created_at": previous["created_at"],
        "new_findings": [],
        "dropped_findings": [],
    }
    assert client.captured["topic"] == "Exact topic"
    assert client.captured["visible_from"] == CUTOFF
    assert client.captured["before_created_at"] == FROZEN
    assert client.captured["previous_now"] == FROZEN


def test_one_added_statement_is_reported_after_whitespace_and_case_normalization(
    monkeypatch,
) -> None:
    base = _record(
        "base",
        FROZEN,
        ["  A   FINDING.  ", "B finding.", "A new finding."],
    )
    previous = _record(
        "previous",
        FROZEN - timedelta(days=7),
        ["a finding.", "B   finding."],
    )
    client = _client(monkeypatch, base, previous)

    response = client.get(PATH.format(report_id="base"))

    assert response.status_code == 200
    body = response.json()
    assert body["new_findings"] == ["A new finding."]
    assert body["dropped_findings"] == []


def test_no_earlier_report_returns_nulls_and_empty_lists(monkeypatch) -> None:
    base = _record("base", FROZEN, ["A finding."])
    client = _client(monkeypatch, base, None)

    response = client.get(PATH.format(report_id="base"))

    assert response.status_code == 200
    assert response.json() == {
        "previous_report_id": None,
        "previous_created_at": None,
        "new_findings": [],
        "dropped_findings": [],
    }


def test_missing_base_report_is_not_found(monkeypatch) -> None:
    client = _client(monkeypatch, None, None)

    response = client.get(PATH.format(report_id="missing"))

    assert response.status_code == 404


@pytest.mark.parametrize("swept", [False, True])
def test_previous_report_expiry_never_exposes_dropped_findings(monkeypatch, swept):
    from tests.unit.test_research_report_repository import FakeRecord, FakeSession
    from trendora.research.repository import get_previous_report_record

    snapshot = _record("old", FROZEN, ["Private expired source detail"])["report"]
    snapshot["research"]["references"] = [{
        "source_code": "youtube",
        "collected_at": (FROZEN - timedelta(days=30)).isoformat(),
    }]
    record = FakeRecord(report=snapshot, created_at=FROZEN - timedelta(days=1))
    if swept:
        record.status = "source_data_expired"
        record.report = {"status": "source_data_expired"}
    before = deepcopy(record.report)
    previous = get_previous_report_record(
        FakeSession([record]), topic=record.topic, before_created_at=FROZEN,
        visible_from=CUTOFF, now=FROZEN,
    )
    assert previous["status"] == "source_data_expired"
    assert previous["report"] == {"status": "source_data_expired"}
    assert record.report == before
    client = _client(monkeypatch, _record("base", FROZEN, ["Current finding"]), previous)
    response = client.get(PATH.format(report_id="base"))
    assert response.status_code == 410
    assert "Private expired" not in response.text
    assert "previous report" in response.json()["error"]["message"].lower()
