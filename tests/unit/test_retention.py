"""Source expiry with synthetic ORM objects only; no engine or database."""

from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from trendora.api.report_snapshot import snapshot_fingerprint
from trendora.models import ContentItem, MetricSnapshot, Publisher, Source
from trendora.models.planner import PlannerPost, PlannerPostActivity, PlannerPostOriginSource
from trendora.models.research import ResearchReportRecord
from trendora.planner import (
    PlannerCreateConflictError,
    _import_selector_hash,
    find_import_replay,
)
from trendora.research.repository import ReportSaveConflictError, save_report_snapshot
from trendora.retention import EXPIRED_STATUS, expire_source_data, report_sources_expired

NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
BOUNDARY = NOW - timedelta(days=30)
ACTOR = uuid4()
SYNTHETIC_SIGNING_KEY = "fictional-recovery-test-key-no-real-value"
YT = uuid4()
OTHER = uuid4()


def _snapshot(collected=BOUNDARY.isoformat(), *, source="youtube"):
    return {
        "status": "completed",
        "research": {
            "query": {"topic": "Fictional research", "sources": [source]},
            "references": [{
                "source_code": source,
                "content_external_id": "source-id",
                "title": "Source title",
                "description": "Source text",
                "url": "https://example.test/source",
                "collected_at": collected,
            }],
        },
        "evidence": {"analyses": ["source-derived evidence"]},
        "interpretation": {"interpretations": ["source-derived interpretation"]},
        "strategy": {"content_gaps": ["source-derived gap"]},
        "ideation": {"content_ideas": ["source-derived idea"]},
    }


def _report(snapshot=None, *, provenance="server_generated"):
    snapshot = deepcopy(snapshot if snapshot is not None else _snapshot())
    return ResearchReportRecord(
        id=uuid4(), created_at=NOW, status="completed", topic="Fictional research",
        markets=["SG"], source_codes=["youtube"],
        date_from=BOUNDARY.date(), date_to=NOW.date(), report=snapshot,
        created_by=ACTOR, save_request_id=uuid4(),
        payload_hash=snapshot_fingerprint(snapshot), snapshot_origin=provenance,
    )


def _post(report):
    post = PlannerPost(
        id=uuid4(), title="My edited title", platform="manual", caption="My caption",
        hook="My hook", creative_brief="My edited brief", asset_links=[],
        notes="My notes", planned_date=None, status="working", assignee_id=None,
        archived_at=None, version=4, content_revision=3, created_by=ACTOR,
        updated_by=ACTOR, create_request_id=uuid4(), created_at=NOW, updated_at=NOW,
        origin={
            "report_id": str(report.id), "item_kind": "idea", "item_index": 0,
            "parent_idea_index": None, "provenance": "server_generated",
            "context": {"title": "Original generated source-derived title"},
            "citations": [{"reference": "source-id"}],
        },
    )
    post.create_payload_hash = _import_selector_hash(_selector(report))
    return post


def _selector(report):
    return {"report_id": str(report.id), "item_kind": "idea", "item_index": 0}


def _origin_source(post, *, collected=BOUNDARY, expires=NOW):
    return PlannerPostOriginSource(
        id=uuid4(), post_id=post.id, source_code="youtube",
        content_external_id="source-id", url="https://example.test/source",
        collected_at=collected, retention_days=30, expires_at=expires, created_at=NOW,
    )


def _content(*, expires=NOW, source=YT):
    return ContentItem(
        id=uuid4(), source_id=source, publisher_id=uuid4(), external_id="video-id",
        content_type="video", title="API title", description="API description",
        url="https://example.test/video", published_at=BOUNDARY, market_id=None,
        source_metadata={"source": "API data"}, retain_until=expires,
    )


def _publisher(*, expires=NOW, source=YT):
    return Publisher(
        id=uuid4(), source_id=source, external_id="channel-id", name="API name",
        url="https://example.test/channel", source_metadata={"source": "API data"},
        retain_until=expires,
    )


def _metric(*, collected=BOUNDARY, expires=NOW, source=YT):
    return MetricSnapshot(
        id=uuid4(), source_id=source, content_item_id=uuid4(), publisher_id=None,
        metric_name="view_count", metric_value=42, observed_at=collected,
        collected_at=collected, retain_until=expires, source_metadata={"raw": 42},
    )


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return list(self.rows)

    def scalar_one_or_none(self):
        assert len(self.rows) <= 1
        return self.rows[0] if self.rows else None


class _Session:
    def __init__(self, *rows):
        self.rows = list(rows)
        self.deletions = []
        self.commits = 0
        self.rollbacks = 0
        self.statements = []
        self.no_autoflush = nullcontext()

    def scalars(self, statement):
        self.statements.append(statement)
        entity = statement.column_descriptions[0]["entity"]
        return _Result([row for row in self.rows if isinstance(row, entity)])

    def execute(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        params = statement.compile().params
        rows = [row for row in self.rows if isinstance(row, entity)]
        for field in ("id", "user_id", "created_by", "save_request_id", "create_request_id"):
            value = params.get(f"{field}_1")
            if value is not None:
                rows = [row for row in rows if getattr(row, field) == value]
        return _Result(rows)

    def query(self, model):
        from sqlalchemy.orm import Query
        self.builder = Query([model])
        return self

    def filter(self, *clauses):
        self.builder = self.builder.filter(*clauses)
        return self

    def first(self):
        return self.execute(self.builder.statement).scalar_one_or_none()

    def begin_nested(self):
        return nullcontext()

    def add(self, row):
        if getattr(row, "id", None) is None:
            row.id = uuid4()
        if getattr(row, "created_at", None) is None:
            row.created_at = NOW
        if isinstance(row, ResearchReportRecord):
            for field in ("date_from", "date_to"):
                value = getattr(row, field)
                if isinstance(value, str):
                    setattr(row, field, date.fromisoformat(value))
        self.rows.append(row)

    def delete(self, row):
        self.deletions.append(row)
        self.rows.remove(row)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def _session(*rows):
    return _Session(Source(id=YT, code="youtube"), Source(id=OTHER, code="github"), *rows)


def _fields(row):
    return deepcopy({key: value for key, value in vars(row).items() if not key.startswith("_")})


def test_default_dry_run_counts_without_mutation_or_transaction_writes():
    report = _report()
    post = _post(report)
    rows = [report, post, _origin_source(post), _content(), _publisher(), _metric()]
    before = [_fields(row) for row in rows]
    session = _session(*rows)
    assert expire_source_data(session, now=NOW) == {
        "reports_expired": 1, "origins_cleared": 1, "origin_sources_deleted": 1,
        "metrics_deleted": 1, "content_cleared": 1, "publishers_cleared": 1,
    }
    assert [_fields(row) for row in rows] == before
    assert not session.deletions
    assert session.commits == session.rollbacks == 0
    assert all(statement._for_update_arg is None for statement in session.statements)


def test_apply_removes_source_payload_preserves_authored_work_and_replay_identity():
    report = _report()
    original_snapshot = deepcopy(report.report)
    post = _post(report)
    original_report = _fields(report)
    original_post = _fields(post)
    origin = _origin_source(post)
    activity = PlannerPostActivity(
        id=uuid4(), post_id=post.id, actor_id=ACTOR, event_type="updated",
        details={"version": 4, "changed_fields": ["title"]}, created_at=NOW,
    )
    original_activity = _fields(activity)
    content, publisher, metric = _content(), _publisher(), _metric()
    session = _session(report, post, origin, content, publisher, metric, activity)
    counts = expire_source_data(session, now=NOW, apply=True)
    assert counts["reports_expired"] == counts["metrics_deleted"] == 1
    assert report.report == {"status": EXPIRED_STATUS, "expired_at": NOW.isoformat()}
    assert report.status == EXPIRED_STATUS
    for field in original_report.keys() - {"report", "status"}:
        assert getattr(report, field) == original_report[field]
    for field in original_post.keys() - {"origin"}:
        assert getattr(post, field) == original_post[field]
    assert post.origin["context"] == {} and post.origin["citations"] == []
    assert post.origin["source_state"] == "expired"
    assert set(session.deletions) == {origin, metric}
    assert _fields(activity) == original_activity
    for row, fields in ((content, ("title", "description", "url", "published_at", "source_metadata")),
                        (publisher, ("name", "url", "source_metadata"))):
        assert all(getattr(row, field) is None for field in fields)
        assert row.external_id == f"retention-expired:{row.id}"
    assert content.publisher_id is not None
    assert session.commits == 0  # Caller owns the atomic transaction.
    from sqlalchemy import inspect
    assert inspect(post).attrs.updated_at.history.added == [original_post["updated_at"]]
    assert all(statement._for_update_arg is not None for statement in session.statements)

    replay, created = save_report_snapshot(
        session, actor_id=ACTOR, request_id=report.save_request_id,
        snapshot=original_snapshot, fingerprint=snapshot_fingerprint(original_snapshot),
        topic=report.topic, markets=report.markets, source_codes=report.source_codes,
        date_from=report.date_from, date_to=report.date_to, status="completed",
        origin="client_supplied",
    )
    assert replay.id == report.id and created is False
    assert find_import_replay(
        session, actor_id=ACTOR, request_id=post.create_request_id, selector=_selector(report)
    ) == post.id
    changed = deepcopy(original_snapshot)
    changed["research"]["query"]["topic"] = "Different operation"
    with pytest.raises(ReportSaveConflictError):
        save_report_snapshot(
            session, actor_id=ACTOR, request_id=report.save_request_id,
            snapshot=changed, fingerprint=snapshot_fingerprint(changed),
            topic=report.topic, markets=[], source_codes=[], date_from=report.date_from,
            date_to=report.date_to, status="completed", origin="client_supplied",
        )
    with pytest.raises(PlannerCreateConflictError):
        find_import_replay(
            session, actor_id=ACTOR, request_id=post.create_request_id,
            selector={**_selector(report), "item_index": 1},
        )


def test_second_apply_is_idempotent():
    report = _report()
    post = _post(report)
    session = _session(report, post, _origin_source(post), _metric(), _content(), _publisher())
    expire_source_data(session, now=NOW, apply=True)
    original_tombstone = deepcopy(report.report)
    assert all(value == 0 for value in expire_source_data(
        session, now=NOW + timedelta(hours=1), apply=True
    ).values())
    assert report.report == original_tombstone


def test_fresh_source_material_is_preserved():
    collected = BOUNDARY + timedelta(seconds=1)
    expiry = NOW + timedelta(seconds=1)
    report = _report(_snapshot(collected.isoformat()))
    post = _post(report)
    rows = [report, post, _origin_source(post, collected=collected, expires=expiry),
            _content(expires=expiry), _publisher(expires=expiry),
            _metric(collected=collected, expires=expiry)]
    before = [_fields(row) for row in rows]
    session = _session(*rows)
    assert all(value == 0 for value in expire_source_data(session, now=NOW, apply=True).values())
    assert [_fields(row) for row in rows] == before
    assert not session.deletions


def test_fresh_generated_report_recovered_after_failed_save_survives_same_time_cleanup(monkeypatch):
    import trendora.api.app as app_module
    import trendora.research.repository as repository_module
    import trendora.research.youtube as youtube_module
    from tests.unit.test_research_reporting import _query, _report_service
    from trendora.api.report_save import ReportSaveRequest, save_report_for_actor
    from trendora.api.research_report_models import ResearchReportRequest, to_report_response
    from trendora.models.membership import Membership
    from trendora.research.repository import get_report_record_by_id

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is not None else NOW.replace(tzinfo=None)

    monkeypatch.setattr(youtube_module, "datetime", FrozenDatetime)
    monkeypatch.setattr(repository_module, "datetime", FrozenDatetime)
    response = to_report_response(_report_service([]).build_report(**_query()))
    snapshot = app_module._snapshot_projection(response)
    assert snapshot["research"]["references"]
    assert all(datetime.fromisoformat(reference["collected_at"].replace("Z", "+00:00")) == NOW
               for reference in snapshot["research"]["references"])
    settings = SimpleNamespace(
        database_url=None, app_env="development", supabase_url=None,
        report_recovery_signing_key=SYNTHETIC_SIGNING_KEY,
    )
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    import trendora.api.report_save as save_module
    monkeypatch.setattr(save_module, "get_settings", lambda: settings)
    outcome = app_module._persist_research_report(
        ResearchReportRequest(**_query()), response, ACTOR,
    )
    assert outcome.status == "failed" and outcome.report_id is None

    session = _session(Membership(user_id=ACTOR, active=True, is_admin=False))
    acknowledgment = save_report_for_actor(
        session, actor_id=ACTOR, body=ReportSaveRequest(
            schema_version=1, request_id=outcome.request_id, snapshot=snapshot,
            recovery_receipt=outcome.recovery_receipt,
        ),
    )
    assert acknowledgment.created and acknowledgment.snapshot_origin == "client_supplied"
    record = next(row for row in session.rows if isinstance(row, ResearchReportRecord))
    counts = expire_source_data(session, now=NOW, apply=True)
    assert counts["reports_expired"] == 0
    readable = get_report_record_by_id(session, acknowledgment.report_id)
    assert readable["report"] == snapshot
    assert record.snapshot_origin == "client_supplied"
    from fastapi.testclient import TestClient
    from tests.support.app import create_test_app
    from trendora.api.deps import get_session
    app = create_test_app()
    app.dependency_overrides[get_session] = lambda: session
    detail = TestClient(app).get(f"/api/v1/research/reports/{acknowledgment.report_id}")
    assert detail.status_code == 200
    assert {field: detail.json()[field] for field in snapshot} == snapshot
    assert detail.json()["persistence"]["snapshot_origin"] == "client_supplied"


def _recover_snapshot(monkeypatch, session, snapshot, *, request_id=None, receipt=None):
    import trendora.research.repository as repository_module
    from trendora.research.recovery import issue_recovery_receipt
    from trendora.retention import report_source_deadline
    request_id = request_id or uuid4()

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is not None else NOW.replace(tzinfo=None)

    monkeypatch.setattr(repository_module, "datetime", FrozenDatetime)
    fingerprint = snapshot_fingerprint(snapshot)
    if receipt is None:
        receipt = issue_recovery_receipt(
            actor_id=ACTOR, request_id=request_id, fingerprint=fingerprint,
            source_expires_at=report_source_deadline(snapshot, now=NOW),
            signing_key=SYNTHETIC_SIGNING_KEY,
        )
    return save_report_snapshot(
        session, actor_id=ACTOR, request_id=request_id, snapshot=snapshot,
        fingerprint=fingerprint, topic="Fictional research", markets=["SG"],
        source_codes=["youtube"], date_from=BOUNDARY.date(), date_to=NOW.date(),
        status="completed", origin="client_supplied", recovery_receipt=receipt,
        signing_key=SYNTHETIC_SIGNING_KEY,
    )


def test_verified_recovery_uses_original_deadline_then_replays_without_restoring_body(monkeypatch):
    snapshot = _snapshot((NOW - timedelta(days=29)).isoformat())
    session = _session()
    report, created = _recover_snapshot(monkeypatch, session, snapshot)
    assert created and report.snapshot_origin == "client_supplied"
    assert report.source_expires_at == NOW + timedelta(days=1)
    post = _post(report)
    post.origin["provenance"] = "client_supplied"
    source = _origin_source(post, collected=NOW - timedelta(days=29), expires=report.source_expires_at)
    session.rows.extend((post, source))
    authored = _fields(post)
    assert all(value == 0 for value in expire_source_data(session, now=NOW, apply=True).values())
    assert report.report == snapshot
    counts = expire_source_data(session, now=report.source_expires_at, apply=True)
    assert counts["reports_expired"] == counts["origins_cleared"] == 1
    assert report.report["status"] == EXPIRED_STATUS
    for field in authored.keys() - {"origin"}:
        assert getattr(post, field) == authored[field]
    replay, created = save_report_snapshot(
        session, actor_id=ACTOR, request_id=report.save_request_id,
        snapshot=snapshot, fingerprint=snapshot_fingerprint(snapshot),
        topic=report.topic, markets=report.markets, source_codes=report.source_codes,
        date_from=report.date_from, date_to=report.date_to, status="completed",
        origin="client_supplied", recovery_receipt=None, signing_key=None,
    )
    assert replay.id == report.id and not created
    assert report.report["status"] == EXPIRED_STATUS


def test_forged_collection_date_does_not_match_genuine_receipt(monkeypatch):
    from trendora.research.recovery import issue_recovery_receipt
    from trendora.research.repository import ReportRecoveryInvalidError
    snapshot = _snapshot((NOW - timedelta(days=29)).isoformat())
    request_id = uuid4()
    receipt = issue_recovery_receipt(
        actor_id=ACTOR, request_id=request_id, fingerprint=snapshot_fingerprint(snapshot),
        source_expires_at=NOW + timedelta(days=1), signing_key=SYNTHETIC_SIGNING_KEY,
    )
    forged = deepcopy(snapshot)
    forged["research"]["references"][0]["collected_at"] = NOW.isoformat()
    session = _session()
    with pytest.raises(ReportRecoveryInvalidError):
        _recover_snapshot(monkeypatch, session, forged, request_id=request_id, receipt=receipt)
    assert not any(isinstance(row, ResearchReportRecord) for row in session.rows)


def test_expired_receipt_cannot_create_a_new_row_under_its_original_key(monkeypatch):
    from trendora.research.repository import ReportSourceExpiredError
    session = _session()
    with pytest.raises(ReportSourceExpiredError):
        _recover_snapshot(monkeypatch, session, _snapshot())
    assert not any(isinstance(row, ResearchReportRecord) for row in session.rows)


def test_genuine_receipt_cannot_be_reused_under_an_independent_operation_key(monkeypatch):
    from trendora.research.recovery import issue_recovery_receipt
    from trendora.research.repository import ReportRecoveryInvalidError
    snapshot = _snapshot(NOW.isoformat())
    receipt = issue_recovery_receipt(
        actor_id=ACTOR, request_id=uuid4(), fingerprint=snapshot_fingerprint(snapshot),
        source_expires_at=NOW + timedelta(days=30), signing_key=SYNTHETIC_SIGNING_KEY,
    )
    session = _session()
    with pytest.raises(ReportRecoveryInvalidError):
        _recover_snapshot(monkeypatch, session, snapshot, request_id=uuid4(), receipt=receipt)
    assert not any(isinstance(row, ResearchReportRecord) for row in session.rows)


def test_original_deadline_uses_oldest_source_instead_of_recovery_or_publication_date():
    from trendora.retention import report_source_deadline
    snapshot = _snapshot(NOW.isoformat())
    older = deepcopy(snapshot["research"]["references"][0])
    older.update(source_code="publicweb", collected_at=(NOW - timedelta(days=10)).isoformat(),
                 published_at=NOW.isoformat())
    snapshot["research"]["references"].append(older)
    assert report_source_deadline(snapshot, now=NOW) == NOW + timedelta(days=20)
    older["collected_at"] = None
    assert report_source_deadline(snapshot, now=NOW) is None


def test_trusted_report_expiry_migration_is_additive_without_backfill(monkeypatch):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "alembic/versions/0008_report_source_expiry.py"
    spec = importlib.util.spec_from_file_location("report_source_expiry_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    calls = []
    monkeypatch.setattr(migration, "op", SimpleNamespace(
        add_column=lambda *args: calls.append(args),
        drop_column=lambda *args: calls.append(args),
    ))
    migration.upgrade()
    assert migration.down_revision == "0007_origin_collected_at_nullable"
    assert len(calls) == 1 and calls[0][0] == "research_reports"
    column = calls[0][1]
    assert column.name == "source_expires_at" and column.nullable
    assert column.type.timezone and column.server_default is None
    migration.downgrade()
    assert calls[1] == ("research_reports", "source_expires_at")


@pytest.mark.parametrize("receipt", ["", "fictional-forged-receipt"])
def test_unverified_fresh_browser_dates_cannot_create_source_recovery(monkeypatch, receipt):
    from trendora.research.repository import ReportRecoveryInvalidError
    session = _session()
    with pytest.raises(ReportRecoveryInvalidError):
        _recover_snapshot(monkeypatch, session, _snapshot(NOW.isoformat()), receipt=receipt)
    assert not any(isinstance(row, ResearchReportRecord) for row in session.rows)


def test_verified_recovered_origin_uses_original_dates_and_caps_every_source():
    from trendora.planner_origin import build_origin_sources
    snapshot = _snapshot(NOW.isoformat())
    origin = {"citations": [{
        "kind": "fact", "reference": {"source_code": "youtube", "content_external_id": "source-id"},
        "field": "title",
    }]}
    deadline = NOW + timedelta(days=1)
    sources = build_origin_sources(
        snapshot, origin, provenance="client_supplied", now=NOW, source_expires_at=deadline,
    )
    assert sources[0]["collected_at"] == NOW
    assert sources[0]["expires_at"] == deadline


@pytest.mark.parametrize("collected", [None, "invalid", "2026-10-04T12:00:00", (NOW + timedelta(seconds=1)).isoformat()])
def test_missing_malformed_naive_or_future_collection_never_establishes_freshness(collected):
    assert report_sources_expired(_snapshot(collected), provenance="server_generated", now=NOW)


@pytest.mark.parametrize("provenance", ["client_supplied", "legacy_unclassified", "unknown"])
def test_untrusted_snapshot_date_does_not_extend_retention(provenance):
    report = _report(_snapshot(NOW.isoformat()), provenance=provenance)
    assert expire_source_data(_session(report), now=NOW, apply=True)["reports_expired"] == 1
    assert report.status == EXPIRED_STATUS


@pytest.mark.parametrize("empty_evidence", [None, {"analyses": [], "patterns": []}])
def test_empty_source_free_report_has_nothing_to_expire(empty_evidence):
    snapshot = _snapshot()
    snapshot["status"] = "no_evidence"
    snapshot["research"]["references"] = []
    for field in ("evidence", "interpretation", "strategy", "ideation"):
        snapshot[field] = None
    snapshot["evidence"] = empty_evidence
    assert not report_sources_expired(snapshot, provenance="legacy_unclassified", now=NOW)


def test_partial_legacy_source_output_without_reference_dates_is_expired():
    snapshot = _snapshot()
    del snapshot["research"]["references"]
    assert report_sources_expired(snapshot, provenance="legacy_unclassified", now=NOW)


def test_expired_marker_cannot_hide_a_remaining_source_payload():
    report = _report()
    report.status = EXPIRED_STATUS
    report.report["status"] = EXPIRED_STATUS
    counts = expire_source_data(_session(report), now=NOW, apply=True)
    assert counts["reports_expired"] == 1
    assert set(report.report) == {"status", "expired_at"}


def test_original_collection_bounds_expiry_even_if_retain_until_was_extended():
    metric = _metric(expires=NOW + timedelta(days=30))
    report = _report(_snapshot(NOW.isoformat()))
    post = _post(report)
    origin = _origin_source(post, expires=NOW + timedelta(days=30))
    session = _session(report, post, metric, origin)
    counts = expire_source_data(session, now=NOW, apply=True)
    assert counts["reports_expired"] == 0
    assert counts["metrics_deleted"] == counts["origin_sources_deleted"] == 1


def test_missing_catalog_expiry_is_conservative_only_for_required_youtube_retention():
    youtube = _content(expires=None)
    other = _content(expires=None, source=OTHER)
    before = _fields(other)
    counts = expire_source_data(_session(youtube, other), now=NOW, apply=True)
    assert counts["content_cleared"] == 1
    assert youtube.title is None and _fields(other) == before


def test_existing_explicit_non_youtube_bounds_are_honored_without_inventing_new_policy():
    metric = _metric(source=OTHER)
    fresh_metric = _metric(source=OTHER, expires=None)
    content = _content(source=OTHER)
    session = _session(metric, fresh_metric, content)
    counts = expire_source_data(session, now=NOW, apply=True)
    assert counts["metrics_deleted"] == counts["content_cleared"] == 1
    assert session.deletions == [metric]


def test_untrusted_origin_context_expires_even_without_sidecars():
    report = _report(_snapshot(NOW.isoformat()))
    post = _post(report)
    post.origin["provenance"] = "client_supplied"
    counts = expire_source_data(_session(report, post), now=NOW, apply=True)
    assert counts["reports_expired"] == 0 and counts["origins_cleared"] == 1
    assert post.title == "My edited title"
    assert post.origin["context"] == {}


def test_expired_report_clears_all_its_origin_sidecars_even_if_one_looks_fresh():
    report = _report()
    post = _post(report)
    origin = _origin_source(post, collected=NOW, expires=NOW + timedelta(days=30))
    session = _session(report, post, origin)
    assert expire_source_data(session, now=NOW, apply=True)["origin_sources_deleted"] == 1
    assert origin in session.deletions


def test_naive_cleanup_clock_is_rejected_before_queries():
    class NoSession:
        def scalars(self, *args):
            raise AssertionError("No queries before current time validation")
    with pytest.raises(ValueError, match="timezone-aware"):
        expire_source_data(NoSession(), now=NOW.replace(tzinfo=None))


@pytest.mark.parametrize("apply", [False, True])
def test_cli_reads_explicit_database_variable_only_and_apply_controls_commit(monkeypatch, capsys, apply):
    import trendora.retention as module

    session = _session()
    disposed = []
    class Engine:
        def dispose(self):
            disposed.append(True)
    calls = []
    monkeypatch.setenv("RETENTION_SYNTHETIC_DATABASE", "postgres://fictional:fictional@127.0.0.1/fictional")
    monkeypatch.setattr(module, "create_engine", lambda url: calls.append(url) or Engine())
    monkeypatch.setattr(module, "Session", lambda engine: session)
    argv = ["--database-env", "RETENTION_SYNTHETIC_DATABASE"] + (["--apply"] if apply else [])
    assert module.main(argv) == 0
    assert len(calls) == 1 and calls[0].startswith("postgresql+psycopg://")
    assert session.commits == int(apply) and session.rollbacks == int(not apply)
    assert disposed == [True]
    output = capsys.readouterr().out
    assert '"mode": "apply"' in output if apply else '"mode": "dry_run"' in output
    assert "fictional" not in output


def test_cli_requires_explicit_target_without_loading_settings_or_building_engine(monkeypatch):
    import trendora.retention as module
    monkeypatch.setattr(module, "create_engine", lambda *args: pytest.fail("Must not connect"))
    with pytest.raises(SystemExit) as error:
        module.main([])
    assert error.value.code == 2


def test_cli_missing_named_database_returns_nonzero_without_connection(monkeypatch):
    import trendora.retention as module
    monkeypatch.delenv("RETENTION_MISSING_DATABASE", raising=False)
    monkeypatch.setattr(module, "create_engine", lambda *args: pytest.fail("Must not connect"))
    assert module.main(["--database-env", "RETENTION_MISSING_DATABASE"]) == 2


def test_cli_failure_is_redacted_and_disposes_engine(monkeypatch, capsys):
    import trendora.retention as module
    from sqlalchemy.exc import SQLAlchemyError
    disposed = []
    class Engine:
        def dispose(self):
            disposed.append(True)
    monkeypatch.setenv("RETENTION_SYNTHETIC_DATABASE", "postgres://fictional:fictional@127.0.0.1/fictional")
    monkeypatch.setattr(module, "create_engine", lambda url: Engine())
    monkeypatch.setattr(module, "Session", lambda engine: _session())
    def fail(*args, **kwargs):
        raise SQLAlchemyError("fictional-secret-must-not-be-printed")
    monkeypatch.setattr(module, "expire_source_data", fail)
    assert module.main(["--database-env", "RETENTION_SYNTHETIC_DATABASE", "--apply"]) == 1
    assert disposed == [True]
    assert "fictional-secret" not in capsys.readouterr().err


@pytest.mark.parametrize("lock", [False, True])
def test_report_import_read_uses_shared_lock_and_refreshes_existing_identity_only_when_requested(lock):
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Query
    from trendora.research.repository import get_report_record_by_id

    report = _report(_snapshot(NOW.isoformat()))
    class QuerySession:
        def query(self, model):
            self.builder = Query([model])  # SQL construction only; no Session or engine.
            return self

        def filter(self, *args):
            self.builder = self.builder.filter(*args)
            return self

        def with_for_update(self, **kwargs):
            self.builder = self.builder.with_for_update(**kwargs)
            return self

        def execution_options(self, **kwargs):
            self.builder = self.builder.execution_options(**kwargs)
            return self

        def first(self):
            return report

    session = QuerySession()
    result = get_report_record_by_id(
        session, str(report.id), visible_from=BOUNDARY, lock_for_import=lock
    )
    assert result["id"] == str(report.id)
    statement = session.builder.statement
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "research_reports.created_at >=" in sql
    assert ("FOR SHARE" in sql) is lock
    assert session.builder._execution_options.get("populate_existing", False) is lock


@pytest.mark.parametrize("replay", [False, True])
def test_import_checks_replay_before_locked_expiry_read(monkeypatch, replay):
    from fastapi.testclient import TestClient
    from tests.support.app import create_test_app
    import trendora.api.planner as planner_api
    import trendora.research.repository as repository
    from trendora.api.deps import get_session

    events = []
    post_id = uuid4()
    def find_replay(*args, **kwargs):
        events.append("replay")
        return post_id if replay else None
    def locked_read(*args, **kwargs):
        assert not replay, "A replay must not resolve or lock its expired source again"
        assert kwargs["lock_for_import"] is True
        events.append("locked_read")
        return {"status": EXPIRED_STATUS, "report": {"status": EXPIRED_STATUS}}
    monkeypatch.setattr(planner_api, "find_import_replay", find_replay)
    monkeypatch.setattr(repository, "get_report_record_by_id", locked_read)
    monkeypatch.setattr(planner_api, "import_post", lambda *a, **k: pytest.fail("Expired source must not import"))
    app = create_test_app()
    app.dependency_overrides[get_session] = lambda: object()
    response = TestClient(app).post("/api/v1/planner/posts/import", json={
        "request_id": str(uuid4()), "report_id": str(uuid4()),
        "item_kind": "idea", "item_index": 0,
    })
    if replay:
        assert response.status_code == 200 and response.json()["id"] == str(post_id)
        assert events == ["replay"]
    else:
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "planner_report_not_found"
        assert events == ["replay", "locked_read"]
