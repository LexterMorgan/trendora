"""P3 Slice B: research-to-planner import mapping, origin, and expiry.

Offline and mocked. Mapping and expiry are pure functions; the route-level
checks use a fake session and a fake report. No database, no provider.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from trendora.planner_origin import (
    ImportOverflowError,
    ImportSelectionError,
    build_origin_sources,
    map_idea,
    purge_expired_origin_sources,
    read_origin,
    resolve_selection,
    source_state,
)

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def _reference(source="youtube", ext="v1", collected="2026-10-01T12:00:00+00:00", url="https://example.com/v1"):
    return {
        "source_code": source,
        "content_external_id": ext,
        "url": url,
        "collected_at": collected,
        "title": "Raw title that must not be copied",
        "description": "Raw description",
    }


def _snapshot():
    return {
        "status": "completed",
        "research": {
            "query": {"topic": "t", "markets": ["SG"], "sources": ["youtube"]},
            "references": [_reference()],
        },
        "evidence": None,
        "interpretation": None,
        "strategy": None,
        "ideation": {
            "content_ideas": [
                {
                    "title": "Idea one",
                    "angle": "Angle one",
                    "opportunity_indexes": [0],
                    "citations": [{"kind": "fact", "reference": {"source_code": "youtube", "content_external_id": "v1"}, "field": "title"}],
                }
            ],
            "content_briefs": [
                {
                    "idea_index": 0,
                    "objective": "Objective",
                    "format": "Reel",
                    "hook": "Hook text",
                    "outline": ["First", "Second"],
                    "citations": [{"kind": "fact", "reference": {"source_code": "youtube", "content_external_id": "v1"}, "field": "title"}],
                }
            ],
        },
    }


class TestMapping:
    def test_idea_maps_title_and_angle(self) -> None:
        fields, origin = resolve_selection(_snapshot(), item_kind="idea", item_index=0)
        assert fields["title"] == "Idea one"
        assert fields["hook"] == ""
        assert fields["creative_brief"].startswith("Angle: Angle one")
        assert origin["item_kind"] == "idea"

    def test_brief_maps_parent_title_and_context(self) -> None:
        fields, origin = resolve_selection(_snapshot(), item_kind="brief", item_index=0)
        assert fields["title"] == "Idea one"
        assert fields["hook"] == "Hook text"
        assert "Objective: Objective" in fields["creative_brief"]
        assert "1. First" in fields["creative_brief"]
        assert origin["parent_idea_index"] == 0

    def test_overflow_raises_rather_than_truncating(self) -> None:
        with pytest.raises(ImportOverflowError):
            map_idea({"title": "x" * 201, "angle": "a"})

    def test_brief_with_missing_parent_is_rejected(self) -> None:
        snapshot = _snapshot()
        snapshot["ideation"]["content_briefs"][0]["idea_index"] = 9
        with pytest.raises(ImportSelectionError):
            resolve_selection(snapshot, item_kind="brief", item_index=0)

    def test_unknown_item_kind_is_rejected(self) -> None:
        with pytest.raises(ImportSelectionError):
            resolve_selection(_snapshot(), item_kind="quotient", item_index=0)


class TestOriginSources:
    def _sources(self, snapshot, origin, *, provenance="server_generated"):
        return build_origin_sources(snapshot, origin, provenance=provenance, now=NOW)

    def test_only_minimal_reference_fields_are_kept(self) -> None:
        _fields, origin = resolve_selection(_snapshot(), item_kind="idea", item_index=0)
        sources = self._sources(_snapshot(), origin)
        assert len(sources) == 1
        source = sources[0]
        assert set(source) >= {
            "source_code",
            "content_external_id",
            "url",
            "collected_at",
            "expires_at",
        }
        assert "title" not in source and "description" not in source

    def test_expiry_uses_collection_time_not_import_time(self) -> None:
        _fields, origin = resolve_selection(_snapshot(), item_kind="idea", item_index=0)
        sources = self._sources(_snapshot(), origin)
        collected = sources[0]["collected_at"]
        assert collected is not None
        assert sources[0]["expires_at"] == collected + timedelta(days=30)

    def test_missing_collection_time_is_unresolved_without_a_manufactured_time(self) -> None:
        snapshot = _snapshot()
        snapshot["research"]["references"][0]["collected_at"] = None
        _fields, origin = resolve_selection(snapshot, item_kind="idea", item_index=0)
        sources = self._sources(snapshot, origin)
        assert sources[0]["collected_at"] is None
        assert sources[0]["expires_at"] == NOW

    def test_future_collection_time_is_unresolved(self) -> None:
        snapshot = _snapshot()
        snapshot["research"]["references"][0]["collected_at"] = "2999-01-01T00:00:00+00:00"
        _fields, origin = resolve_selection(snapshot, item_kind="idea", item_index=0)
        sources = self._sources(snapshot, origin)
        assert sources[0]["collected_at"] is None

    def test_client_supplied_recent_timestamp_cannot_establish_freshness(self) -> None:
        """A client-claimed recent collected_at must not become available."""
        snapshot = _snapshot()
        snapshot["research"]["references"][0]["collected_at"] = NOW.isoformat()
        _fields, origin = resolve_selection(snapshot, item_kind="idea", item_index=0)
        sources = self._sources(snapshot, origin, provenance="client_supplied")
        assert sources[0]["collected_at"] is None
        assert sources[0]["expires_at"] == NOW
        assert source_state(
            collected_at=sources[0]["collected_at"],
            expires_at=sources[0]["expires_at"],
            now=NOW,
        ) == "unresolved"

    def test_legacy_unclassified_timestamp_cannot_establish_freshness(self) -> None:
        snapshot = _snapshot()
        snapshot["research"]["references"][0]["collected_at"] = NOW.isoformat()
        _fields, origin = resolve_selection(snapshot, item_kind="idea", item_index=0)
        sources = self._sources(snapshot, origin, provenance="legacy_unclassified")
        assert sources[0]["collected_at"] is None

    def test_pattern_only_citation_keeps_its_source_connection(self) -> None:
        """A pattern citation has no reference field; resolve it via the pack."""
        snapshot = _snapshot()
        snapshot["evidence"] = {
            "analyses": [],
            "patterns": [
                {
                    "observation_type": "description_has_url",
                    "analyzed_count": 1,
                    "matching_count": 1,
                    "non_matching_count": 0,
                    "ratio": 1.0,
                    "matching_reference_ids": [
                        {"source_code": "youtube", "content_external_id": "v1"}
                    ],
                    "non_matching_reference_ids": [],
                }
            ],
        }
        snapshot["ideation"]["content_ideas"][0]["citations"] = [
            {"kind": "pattern", "observation_type": "description_has_url"}
        ]
        _fields, origin = resolve_selection(snapshot, item_kind="idea", item_index=0)
        sources = self._sources(snapshot, origin)
        assert [s["content_external_id"] for s in sources] == ["v1"]

    def test_expired_state_when_past_deadline(self) -> None:
        assert source_state(
            collected_at=NOW - timedelta(days=31),
            expires_at=NOW - timedelta(days=1),
            now=NOW,
        ) == "expired"

    def test_available_state_when_fresh(self) -> None:
        assert source_state(
            collected_at=NOW - timedelta(days=1),
            expires_at=NOW + timedelta(days=29),
            now=NOW,
        ) == "available"


class _Source:
    def __init__(self, state="available", *, collected_at=None, expires_at=None):
        self.source_code = "youtube"
        self.content_external_id = "v1"
        self.url = "https://example.com/v1"
        if state == "available":
            self.collected_at = collected_at or (NOW - timedelta(days=1))
            self.expires_at = expires_at or (NOW + timedelta(days=29))
        elif state == "expired":
            self.collected_at = collected_at or (NOW - timedelta(days=31))
            self.expires_at = expires_at or (NOW - timedelta(days=1))
        else:  # unresolved
            self.collected_at = None
            self.expires_at = expires_at or NOW


class _Post:
    def __init__(self, origin="default"):
        if origin == "default":
            origin = {
                "report_id": str(uuid4()),
                "item_kind": "idea",
                "item_index": 0,
                "provenance": "server_generated",
                "context": {"title": "T"},
            }
        self.origin = origin


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _ReadSession:
    def __init__(self, post, sources):
        self._post = post
        self._sources = sources

    def get(self, model, pk):
        return self._post

    def execute(self, statement, *args, **kwargs):
        return _Result(self._sources)

    def delete(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError


class TestOriginRead:
    def test_restricted_hides_source_urls_but_keeps_context(self) -> None:
        origin = read_origin(
            _ReadSession(_Post(), [_Source()]),
            post_id=uuid4(),
            now=NOW,
            can_read_report=False,
        )
        assert origin["context"]["title"] == "T"
        assert origin["sources"][0]["state"] == "restricted"
        assert origin["sources"][0]["url"] is None

    def test_accessible_shows_available_source(self) -> None:
        origin = read_origin(
            _ReadSession(_Post(), [_Source()]),
            post_id=uuid4(),
            now=NOW,
            can_read_report=True,
        )
        assert origin["sources"][0]["state"] == "available"
        assert origin["sources"][0]["url"] == "https://example.com/v1"

    def test_manual_post_has_no_origin(self) -> None:
        origin = read_origin(
            _ReadSession(_Post(origin=None), []),
            post_id=uuid4(),
            now=NOW,
            can_read_report=True,
        )
        assert origin is None

    def test_expired_source_is_suppressed(self) -> None:
        origin = read_origin(
            _ReadSession(_Post(), [_Source(state="expired")]),
            post_id=uuid4(),
            now=NOW,
            can_read_report=True,
        )
        assert origin["sources"][0]["state"] == "expired"
        assert origin["sources"][0]["url"] is None

    def test_unresolved_source_is_not_available(self) -> None:
        origin = read_origin(
            _ReadSession(_Post(), [_Source(state="unresolved")]),
            post_id=uuid4(),
            now=NOW,
            can_read_report=True,
        )
        assert origin["sources"][0]["state"] == "unresolved"
        assert origin["sources"][0]["url"] is None

    def test_restricted_keeps_authored_context_even_with_expired_source(self) -> None:
        origin = read_origin(
            _ReadSession(_Post(), [_Source(state="expired")]),
            post_id=uuid4(),
            now=NOW,
            can_read_report=False,
        )
        assert origin["context"]["title"] == "T"
        assert origin["sources"][0]["state"] == "restricted"


class TestPurge:
    def test_purge_deletes_only_expired_source_rows(self) -> None:
        captured = {}

        class _DeleteSession:
            def __init__(self):
                self.deleted = 0

            def execute(self, statement, *args, **kwargs):
                self.deleted += 1
                captured["statement"] = statement
                class _R:
                    rowcount = 2
                return _R()

        session = _DeleteSession()
        removed = purge_expired_origin_sources(session, NOW)
        assert removed == 2
        assert session.deleted == 1
        # Cleanup targets only the origin sidecar, never the authored post.
        assert "planner_post_origin_sources" in str(captured["statement"])
        assert "planner_posts" not in str(captured["statement"]).replace(
            "planner_post_origin_sources", ""
        )


class _ImportSession:
    """Fake session for the import route: ordered scalar results."""

    def __init__(self, scalars=None, membership=None):
        self._scalars = list(scalars or [])
        self._membership = membership
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0

    def execute(self, statement, *args, **kwargs):
        text = str(statement)
        if "FOR SHARE" in text or "memberships" in text:
            return _ScalarResult(self._membership)
        if self._scalars:
            return _ScalarResult(self._scalars.pop(0))
        raise AssertionError(f"unexpected statement: {text}")

    def get(self, model, pk):
        return None

    def add(self, record):
        self.added.append(record)

    def flush(self):
        self.flushes += 1
        for record in self.added:
            if getattr(record, "id", None) is None:
                record.id = uuid4()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class _ScalarResult:
    def __init__(self, scalar):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return []


def _import_client(monkeypatch, session, member=None):
    from fastapi.testclient import TestClient as _TC
    from tests.support.app import TEST_MEMBER, create_test_app

    app = create_test_app(member or TEST_MEMBER)
    from trendora.api.app import get_session

    app.dependency_overrides[get_session] = lambda: session
    return _TC(app)


class TestImportRouteAccess:
    def test_inaccessible_report_returns_404(self, monkeypatch) -> None:
        from tests.support.app import TEST_MEMBER
        from trendora.api import planner as planner_api

        monkeypatch.setattr(
            planner_api, "find_import_replay", lambda *a, **k: None
        )
        # get_report_record_by_id returns None because visibility excludes it.
        import trendora.research.repository as repo

        monkeypatch.setattr(repo, "get_report_record_by_id", lambda *a, **k: None)
        session = _ImportSession(membership=_member_row(TEST_MEMBER.user_id))
        client = _import_client(monkeypatch, session)
        response = client.post(
            "/api/v1/planner/posts/import",
            json={
                "request_id": str(uuid4()),
                "report_id": str(uuid4()),
                "item_kind": "idea",
                "item_index": 0,
            },
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "planner_report_not_found"

    def test_replay_returns_200_without_resolving_source(self, monkeypatch) -> None:
        from tests.support.app import TEST_MEMBER
        from trendora.api import planner as planner_api

        post_id = uuid4()
        monkeypatch.setattr(
            planner_api, "find_import_replay", lambda *a, **k: post_id
        )
        import trendora.research.repository as repo

        def _explode(*a, **k):  # pragma: no cover - must not run on replay
            raise AssertionError("source must not be resolved on replay")

        monkeypatch.setattr(repo, "get_report_record_by_id", _explode)
        session = _ImportSession(membership=_member_row(TEST_MEMBER.user_id))
        client = _import_client(monkeypatch, session)
        response = client.post(
            "/api/v1/planner/posts/import",
            json={
                "request_id": str(uuid4()),
                "report_id": str(uuid4()),
                "item_kind": "brief",
                "item_index": 0,
            },
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(post_id)


def _member_row(user_id):
    from types import SimpleNamespace

    return SimpleNamespace(
        user_id=user_id,
        email="m@example.com",
        active=True,
        is_admin=False,
        can_approve=False,
    )
