"""Signed recovery and source cleanup on the owner-approved scratch database."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session, sessionmaker

from tests.integration.test_planner import (
    ACTOR, ASSIGNEE, _payload, _run_many, _seed_members, _update, planner_rows,
)
from tests.pg_harness import approved_test_target_or_skip, libpq_free_env, run_checked
from tests.support.app import create_test_app
from tests.unit.test_report_save_recovery import _valid_snapshot
from trendora.api.auth import Member
from trendora.api.deps import get_session
from trendora.api.planner import ImportRequest
from trendora.api.report_save import (
    ReportExpiredError, ReportSaveConflictErrorApi, ReportSaveInvalidError,
    ReportSaveRequest, save_report_for_actor,
)
from trendora.api.report_snapshot import snapshot_fingerprint
from trendora.models import ContentItem, MetricSnapshot, Publisher, Source
from trendora.models.planner import PlannerPost, PlannerPostActivity, PlannerPostOriginSource
from trendora.models.research import ResearchReportRecord
from trendora.planner import create_post, update_post
from trendora.research.recovery import issue_recovery_receipt
from trendora.retention import EXPIRED_STATUS, report_source_deadline

pytestmark = pytest.mark.integration
KEY = "fictional-disposable-recovery-signing-key-only"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def report_rows(approved_engine, planner_rows, monkeypatch):
    import trendora.api.report_save as save_module

    def wipe():
        with Session(approved_engine) as session:
            session.execute(text(
                "TRUNCATE research_reports, metric_snapshots, content_item_topics, "
                "content_items, publishers, sources"
            ))
            session.commit()

    wipe()
    with Session(approved_engine) as session:
        _seed_members(session)
    monkeypatch.setattr(save_module, "get_settings", lambda: SimpleNamespace(
        report_recovery_signing_key=KEY,
    ))
    yield
    wipe()


def _snapshot(collected):
    snapshot = _valid_snapshot()
    for reference in snapshot["research"]["references"]:
        reference["collected_at"] = collected.isoformat()
    return snapshot


def _body(snapshot, request_id=None, *, actor=ACTOR, deadline=None):
    request_id = request_id or uuid4()
    return ReportSaveRequest(
        schema_version=1, request_id=request_id, snapshot=snapshot,
        recovery_receipt=issue_recovery_receipt(
            actor_id=actor, request_id=request_id,
            fingerprint=snapshot_fingerprint(snapshot),
            source_expires_at=deadline or report_source_deadline(
                snapshot, now=datetime.now(timezone.utc),
            ),
            signing_key=KEY,
        ),
    )


@pytest.fixture
def client(approved_engine, report_rows):
    member = Member(user_id=ACTOR, email="fictional@example.test", active=True,
                    is_admin=False, can_approve=False)
    app = create_test_app(member)

    def session_dependency():
        with Session(approved_engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("persisted", [False, True])
def test_generation_recovery_keeps_identity_and_original_deadline(
    approved_engine, report_rows, monkeypatch, persisted,
):
    import trendora.api.app as app_module
    from trendora.api.research_report_models import ResearchReportRequest, ResearchReportResponse

    now = datetime.now(timezone.utc)
    snapshot = _snapshot(now - timedelta(days=29))
    response = ResearchReportResponse.model_validate(snapshot)
    snapshot = app_module._snapshot_projection(response)
    request_id = uuid4()
    monkeypatch.setattr(app_module, "uuid4", lambda: request_id)
    monkeypatch.setattr(app_module, "get_utc_now", lambda: now)
    monkeypatch.setattr(app_module, "get_settings", lambda: SimpleNamespace(
        database_url=os.environ["TRENDORA_TEST_DATABASE_URL"] if persisted else None,
        report_recovery_signing_key=KEY,
    ))
    monkeypatch.setattr(app_module, "get_session_factory", lambda: sessionmaker(approved_engine))
    outcome = app_module._persist_research_report(
        ResearchReportRequest(**snapshot["research"]["query"]), response, ACTOR,
    )
    assert outcome.status == ("saved" if persisted else "failed")
    assert outcome.recovery_receipt
    body = ReportSaveRequest(schema_version=1, request_id=outcome.request_id,
                             snapshot=snapshot, recovery_receipt=outcome.recovery_receipt)
    with Session(approved_engine) as session:
        saved = save_report_for_actor(session, actor_id=ACTOR, body=body)
        replay = save_report_for_actor(session, actor_id=ACTOR, body=body)
        assert saved.created is not persisted and not replay.created
        assert saved.report_id == replay.report_id
        if persisted:
            assert saved.report_id == outcome.report_id
        row = session.get(ResearchReportRecord, UUID(saved.report_id))
        assert row.source_expires_at == now + timedelta(days=1)
        assert row.report == snapshot and row.payload_hash == snapshot_fingerprint(snapshot)
        assert row.snapshot_origin == ("server_generated" if persisted else "client_supplied")
        assert session.query(ResearchReportRecord).count() == 1


@pytest.mark.parametrize("mode", ["identical", "conflicting", "independent"])
def test_concurrent_report_saves(approved_engine, report_rows, monkeypatch, mode):
    import trendora.research.repository as repository

    snapshot = _snapshot(datetime.now(timezone.utc))
    second = deepcopy(snapshot)
    if mode == "conflicting":
        second["research"]["query"]["topic"] = "Other fictional research"
    first = _body(snapshot)
    second = _body(second, None if mode == "independent" else first.request_id)
    barrier = threading.Barrier(2)
    original = repository.find_report_by_key

    def synchronized_find(session, **kwargs):
        result = original(session, **kwargs)
        if not session.info.get("initial_lookup_done"):
            session.info["initial_lookup_done"] = True
            assert result is None
            barrier.wait(10)
        return result

    monkeypatch.setattr(repository, "find_report_by_key", synchronized_find)
    outcomes = []

    def worker(body):
        def save():
            with Session(approved_engine) as session:
                outcomes.append(save_report_for_actor(session, actor_id=ACTOR, body=body))
        return save

    errors = _run_many([worker(first), worker(second)])
    if mode == "conflicting":
        assert len(errors) == 1 and isinstance(errors[0], ReportSaveConflictErrorApi)
        assert len(outcomes) == 1 and outcomes[0].created
    else:
        assert errors == []
        assert len(outcomes) == 2
        assert sorted(outcome.created for outcome in outcomes) == (
            [False, True] if mode == "identical" else [True, True]
        )
    expected = 2 if mode == "independent" else 1
    assert len({outcome.report_id for outcome in outcomes}) == expected
    with Session(approved_engine) as session:
        assert session.query(ResearchReportRecord).count() == expected


@pytest.mark.parametrize("mode", ["missing_key", "forged_snapshot", "other_actor", "expired"])
def test_rejected_recovery_never_inserts(approved_engine, report_rows, monkeypatch, mode):
    import trendora.api.report_save as save_module

    now = datetime.now(timezone.utc)
    snapshot = _snapshot(now)
    body = _body(snapshot, deadline=now - timedelta(seconds=1) if mode == "expired" else None)
    if mode == "missing_key":
        monkeypatch.setattr(save_module, "get_settings", lambda: SimpleNamespace(
            report_recovery_signing_key=None,
        ))
    if mode == "forged_snapshot":
        body.snapshot["research"]["references"][0]["collected_at"] = (now - timedelta(days=1)).isoformat()
    with Session(approved_engine) as session:
        with pytest.raises(ReportExpiredError if mode == "expired" else ReportSaveInvalidError):
            save_report_for_actor(session, actor_id=ASSIGNEE if mode == "other_actor" else ACTOR, body=body)
        assert session.query(ResearchReportRecord).count() == 0


def test_planner_uuid_defaults_are_executed_by_postgresql(approved_engine, report_rows):
    with Session(approved_engine) as session:
        defaults = dict(session.execute(text(
            "SELECT table_name, column_default FROM information_schema.columns "
            "WHERE table_schema='public' AND column_name='id' "
            "AND table_name IN ('planner_posts','planner_post_activity')"
        )).all())
        assert set(defaults) == {"planner_posts", "planner_post_activity"}
        assert all("gen_random_uuid()" in value for value in defaults.values())
        post_id, created = create_post(session, actor_id=ACTOR, data=_payload(uuid4()))
        activity = session.query(PlannerPostActivity).one()
        assert created and post_id.version == activity.id.version == 4
        assert activity.post_id == post_id and activity.id != post_id


def test_retention_cli_preserves_authored_content_and_replay(approved_engine, client):
    now = datetime.now(timezone.utc)
    snapshot = _snapshot(now - timedelta(days=31))
    body = _body(snapshot)
    with Session(approved_engine) as session:
        record = ResearchReportRecord(
            status=snapshot["status"], topic="Fictional expired source", markets=["SG"],
            source_codes=["youtube"], date_from=now.date(), date_to=now.date(),
            report=snapshot, created_by=ACTOR, save_request_id=body.request_id,
            payload_hash=snapshot_fingerprint(snapshot), snapshot_origin="server_generated",
            source_expires_at=now - timedelta(days=1),
        )
        session.add(record)
        session.commit()
        report_id = record.id
    assert client.get(f"/api/v1/research/reports/{report_id}").status_code == 200
    import_body = ImportRequest(request_id=uuid4(), report_id=report_id,
                                item_kind="idea", item_index=0).model_dump(mode="json")
    imported = client.post("/api/v1/planner/posts/import", json=import_body)
    assert imported.status_code == 201, imported.text
    post_id = UUID(imported.json()["id"])
    with Session(approved_engine) as session:
        update_post(session, actor_id=ACTOR, post_id=post_id, data=_update(
            1, title="My authored title", caption="My authored caption", hook="My hook",
            creative_brief="My brief", notes="My notes", planned_date=now.date(),
            asset_links=["https://example.test/authored-asset"], status="working",
        ))
        post = session.get(PlannerPost, post_id)
        authored = {column.key: deepcopy(getattr(post, column.key)) for column in inspect(PlannerPost).columns
                    if column.key != "origin"}
        activity = [(row.id, row.details, row.created_at) for row in
                    session.query(PlannerPostActivity).order_by(PlannerPostActivity.id).all()]
        source_count = session.query(PlannerPostOriginSource).count()
        assert source_count > 0
        source = Source(code="youtube", name="Fictional", classification="synthetic")
        session.add(source)
        session.flush()
        publisher = Publisher(source_id=source.id, external_id="fictional-channel", name="Source name",
                              url="https://example.test/channel", source_metadata={"source": "fictional"},
                              retain_until=now - timedelta(days=1))
        session.add(publisher)
        session.flush()
        content = ContentItem(source_id=source.id, publisher_id=publisher.id, external_id="fictional-video",
                              content_type="video", title="Source title", description="Source description",
                              url="https://example.test/video", published_at=now, source_metadata={"source": "fictional"},
                              retain_until=now - timedelta(days=1))
        session.add(content)
        session.flush()
        session.add(MetricSnapshot(source_id=source.id, content_item_id=content.id,
                                   metric_name="view_count", metric_value=42, observed_at=now,
                                   collected_at=now - timedelta(days=31), retain_until=now - timedelta(days=1)))
        session.commit()
    target = approved_test_target_or_skip(os.environ["TRENDORA_TEST_DATABASE_URL"])
    env = libpq_free_env(os.environ)
    env["TRENDORA_RETENTION_DATABASE_URL"] = target.url_for(target.database)
    command = [sys.executable, "-B", "-m", "trendora.retention", "--database-env", "TRENDORA_RETENTION_DATABASE_URL"]
    expected = dict(reports_expired=1, origins_cleared=1, origin_sources_deleted=source_count,
                    metrics_deleted=1, content_cleared=1, publishers_cleared=1)
    dry = json.loads(run_checked(command, cwd=ROOT, env=env, timeout=60, secrets=target.secrets))
    assert dry == {"mode": "dry_run", **expected}
    with Session(approved_engine) as session:
        assert session.get(ResearchReportRecord, report_id).report == snapshot
        assert session.query(PlannerPostOriginSource).count() == source_count
        assert session.query(MetricSnapshot).count() == 1
    applied = json.loads(run_checked(command + ["--apply"], cwd=ROOT, env=env, timeout=60, secrets=target.secrets))
    assert applied == {"mode": "apply", **expected}
    with Session(approved_engine) as session:
        record = session.get(ResearchReportRecord, report_id)
        assert record.status == EXPIRED_STATUS and set(record.report) == {"status", "expired_at"}
        assert record.source_expires_at == now - timedelta(days=1)
        assert record.payload_hash == snapshot_fingerprint(snapshot)
        post = session.get(PlannerPost, post_id)
        assert all(getattr(post, key) == value for key, value in authored.items())
        assert post.origin["context"] == {} and post.origin["citations"] == []
        assert [(row.id, row.details, row.created_at) for row in
                session.query(PlannerPostActivity).order_by(PlannerPostActivity.id).all()] == activity
        assert session.query(PlannerPostOriginSource).count() == session.query(MetricSnapshot).count() == 0
        for model, fields in ((ContentItem, ("title", "description", "url", "published_at", "source_metadata")),
                              (Publisher, ("name", "url", "source_metadata"))):
            row = session.query(model).one()
            assert row.external_id == f"retention-expired:{row.id}"
            assert all(getattr(row, field) is None for field in fields)
        replay = save_report_for_actor(session, actor_id=ACTOR, body=body)
        assert not replay.created and replay.report_id == str(report_id)
        assert session.get(ResearchReportRecord, report_id).status == EXPIRED_STATUS
        new_body = _body(snapshot)
        with pytest.raises(ReportExpiredError):
            save_report_for_actor(session, actor_id=ACTOR, body=new_body)
        assert session.query(ResearchReportRecord).count() == 1
    expired = client.get(f"/api/v1/research/reports/{report_id}")
    assert expired.status_code == 410 and expired.json()["error"]["code"] == "report_expired"
    replay = client.post("/api/v1/planner/posts/import", json=import_body)
    assert replay.status_code == 200 and replay.json()["id"] == str(post_id)
    import_body["request_id"] = str(uuid4())
    assert client.post("/api/v1/planner/posts/import", json=import_body).status_code == 404
