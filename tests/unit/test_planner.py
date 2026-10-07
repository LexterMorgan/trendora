"""Offline planner contracts and transaction regressions (P2A Task 2).

Validation runs against Pydantic only. Transaction behaviour runs against a
recording fake session: no engine, no connection, no subprocess. These pin the
service rules the real PostgreSQL checks will later confirm: retry-safe
creation keyed on ``(created_by, create_request_id)``, atomic version
predicates, conflict-on-stale-no-op, exactly one activity row per real
mutation, and rollback-without-success on commit or activity failure.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.result import result_tuple
from sqlalchemy.exc import OperationalError

from trendora.planner import (
    PlannerAssigneeInvalidError,
    PlannerCreateConflictError,
    PlannerPostArchivedError,
    PlannerPostNotFoundError,
    PlannerVersionConflictError,
    PostCreate,
    PostFields,
    PostUpdate,
    PostVersionRequest,
    _lock_members,
    _payload_hash,
    create_post,
    set_archived,
    update_post,
)
from trendora.api.errors import AuthInactiveError, AuthNotMemberError, DataUnavailableError

ACTOR = UUID("00000000-0000-4000-8000-000000000001")
OTHER = UUID("00000000-0000-4000-8000-000000000002")
POST_ID = UUID("00000000-0000-4000-8000-000000000003")
REQUEST_ID = UUID("00000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc)
SECRET = "hunter2-s3cret"
DRIVER_DETAIL = f"insert failed; password={SECRET}"

FIELDS: dict[str, object] = {
    "title": "Launch teaser",
    "platform": "Instagram",
    "caption": "First caption",
    "hook": "Stop scrolling",
    "creative_brief": "Bright studio shot",
    "asset_links": ["https://example.com/asset"],
    "notes": "Internal note",
    "planned_date": None,
    "assignee_id": None,
}


def _fields(**overrides: object) -> dict[str, object]:
    payload = dict(FIELDS)
    payload.update(overrides)
    return payload


def _post(**overrides: object) -> SimpleNamespace:
    row = {
        "id": POST_ID,
        "title": "Launch teaser",
        "platform": "Instagram",
        "caption": "First caption",
        "hook": "Stop scrolling",
        "creative_brief": "Bright studio shot",
        "asset_links": ["https://example.com/asset"],
        "notes": "Internal note",
        "planned_date": None,
        "assignee_id": None,
        "status": "idea",
        "version": 1,
        "content_revision": 1,
        "created_by": OTHER,
        "updated_by": OTHER,
        "created_at": NOW,
        "updated_at": NOW,
        "archived_at": None,
        "create_request_id": REQUEST_ID,
        "create_payload_hash": "0" * 64,
    }
    row.update(overrides)
    return SimpleNamespace(**row)


MembershipRow = result_tuple(["Membership"])


class _EntityResult:
    """``result.scalars()`` view: mapped objects, never ``Row`` wrappers."""

    def __init__(self, entities: list) -> None:
        self._entities = entities

    def all(self) -> list:
        return list(self._entities)


class FakeResult:
    """Stands in for the ``Result`` of an ORM SELECT.

    ``entities`` are the mapped objects a single-entity SELECT returned, so
    ``.all()`` wraps each one in a real ``Row`` keyed by the entity name while
    ``.scalars()`` hands the objects back unwrapped, exactly like
    ``session.execute(select(Membership))``. Reading a column straight off the
    ``Row`` (``row.user_id``) raises ``AttributeError``, as it does on a live
    connection: column attributes live on the entity, not the ``Row``.
    """

    def __init__(self, scalar: object = None, entities: list | None = None) -> None:
        self._scalar = scalar
        self._entities = entities if entities is not None else []

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def scalars(self) -> _EntityResult:
        return _EntityResult(self._entities)

    def all(self) -> list:
        return [MembershipRow([entity]) for entity in self._entities]


class RecordingSession:
    """Minimal session seam: statements consumed in order, calls recorded."""

    def __init__(self, results: list) -> None:
        self._results = list(results)
        self.statements: list[object] = []
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0
        self.flush_error: BaseException | None = None
        self.commit_error: BaseException | None = None

    def execute(self, statement, *args, **kwargs) -> FakeResult:
        self.statements.append(statement)
        if not self._results:
            raise AssertionError(f"unexpected statement: {statement}")
        item = self._results.pop(0)
        if isinstance(item, BaseException):
            raise item
        assert isinstance(item, FakeResult), item
        return item

    def add(self, object_) -> None:
        self.added.append(object_)

    def flush(self) -> None:
        self.flushes += 1
        if self.flush_error is not None:
            raise self.flush_error

    def commit(self) -> None:
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        self.rollbacks += 1

    def sql(self) -> list[str]:
        return [str(statement) for statement in self.statements]


def _membership(user_id: UUID, *, active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(user_id=user_id, active=active)


def _db_error() -> OperationalError:
    return OperationalError("insert planner_posts", {}, Exception(DRIVER_DETAIL))


class TestPostFieldsValidation:
    def test_post_fields_reject_invalid_boundaries(self) -> None:
        valid = _fields()

        with pytest.raises(ValidationError):
            PostFields(**_fields(title=""))
        with pytest.raises(ValidationError):
            PostFields(**_fields(title="   "))
        with pytest.raises(ValidationError):
            PostFields(**_fields(title="t" * 201))
        with pytest.raises(ValidationError):
            PostFields(**_fields(platform="p" * 81))
        with pytest.raises(ValidationError):
            PostFields(**_fields(hook="h" * 1001))
        with pytest.raises(ValidationError):
            PostFields(**_fields(caption="c" * 20001))
        with pytest.raises(ValidationError):
            PostFields(**_fields(creative_brief="b" * 20001))
        with pytest.raises(ValidationError):
            PostFields(**_fields(notes="n" * 20001))
        with pytest.raises(ValidationError):
            PostFields(**_fields(asset_links=["https://example.com"] * 21))
        with pytest.raises(ValidationError):
            PostFields(**_fields(asset_links=["https://example.com/" + "a" * 2048]))

        with pytest.raises(ValidationError):
            PostFields(**_fields(caption=42))
        with pytest.raises(ValidationError):
            PostFields(**_fields(hook=True))
        with pytest.raises(ValidationError):
            PostFields(**_fields(asset_links=[1]))

        with pytest.raises(ValidationError):
            PostFields(**_fields(asset_links=["ftp://example.com/a"]))
        with pytest.raises(ValidationError):
            PostFields(**_fields(asset_links=["not-a-url"]))
        with pytest.raises(ValidationError):
            PostFields(**_fields(asset_links=["https:///missing-host"]))
        with pytest.raises(ValidationError):
            PostFields(**_fields(asset_links=["https://user:pass@example.com/a"]))

        with pytest.raises(ValidationError):
            PostFields(**_fields(planned_date="2026-10-01T00:00:00"))
        with pytest.raises(ValidationError):
            PostFields(**_fields(planned_date="2026-10-1"))
        with pytest.raises(ValidationError):
            PostFields(**_fields(planned_date=1791000000))
        with pytest.raises(ValidationError):
            PostFields(**_fields(planned_date="2026-10-01T00:00:00Z"))

        with pytest.raises(ValidationError):
            PostFields(**_fields(assignee_id="not-a-uuid"))
        with pytest.raises(ValidationError):
            PostFields(**_fields(computed_by="server"))
        with pytest.raises(ValidationError):
            PostFields(**_fields(created_by=ACTOR))

        accepted = PostFields(**_fields())
        assert accepted.title == "Launch teaser"
        assert accepted.planned_date is None and accepted.assignee_id is None
        assert accepted.asset_links == ["https://example.com/asset"]

        trimmed = PostFields(**_fields(title="  Padded title  ", platform="  IG  "))
        assert trimmed.title == "Padded title" and trimmed.platform == "IG"

        blank_ok = PostFields(**_fields(platform="", asset_links=[]))
        assert blank_ok.platform == "" and blank_ok.asset_links == []

        dated = PostFields(**_fields(planned_date="2026-12-31"))
        assert dated.planned_date == date(2026, 12, 31)
        assert valid["title"] == PostFields(**valid).title

    def test_versions_are_strict_positive_integers(self) -> None:
        for bad in (True, False, "3", 0, -1, 1.5):
            with pytest.raises(ValidationError):
                PostUpdate(**_fields(expected_version=bad, status="idea"))
            with pytest.raises(ValidationError):
                PostVersionRequest(expected_version=bad)
        assert PostVersionRequest(expected_version=2).expected_version == 2

    def test_create_and_update_shapes_are_complete(self) -> None:
        with pytest.raises(ValidationError):
            PostCreate(**_fields())
        created = PostCreate(**_fields(request_id=REQUEST_ID))
        assert created.request_id == REQUEST_ID

        with pytest.raises(ValidationError):
            PostUpdate(**_fields(expected_version=1))
        with pytest.raises(ValidationError):
            PostUpdate(**_fields(expected_version=1, status="published"))
        with pytest.raises(ValidationError):
            PostUpdate(**_fields(expected_version=1, status="ready"))
        updated = PostUpdate(**_fields(expected_version=1, status="working"))
        assert updated.status == "working"


def _create_session(results: list) -> RecordingSession:
    return RecordingSession(results)


def _create_data(**overrides: object) -> PostCreate:
    payload = _fields(request_id=REQUEST_ID)
    payload.update(overrides)
    return PostCreate(**payload)


class TestCreationIsRetrySafe:
    def test_creation_replay_keeps_original_id_after_edit_or_archive(
        self,
    ) -> None:
        data = _create_data(assignee_id=OTHER)
        stored = _post(
            title="Edited after creation",
            archived_at=NOW,
            version=3,
            create_payload_hash=_payload_hash(data),
        )
        session = _create_session(
            [
                FakeResult(entities=[_membership(ACTOR), _membership(OTHER)]),
                FakeResult(scalar=stored),
            ]
        )

        post_id, created = create_post(session, actor_id=ACTOR, data=data)

        assert (post_id, created) == (POST_ID, False)
        assert session.commits == 0
        assert session.added == []
        assert session.flushes == 0
        assert session.rollbacks == 0

    def test_creation_key_with_changed_payload_conflicts(self) -> None:
        session = _create_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=_post(title="A different draft")),
            ]
        )

        with pytest.raises(PlannerCreateConflictError):
            create_post(session, actor_id=ACTOR, data=_create_data())

        assert session.commits == 0
        assert session.added == []
        assert session.rollbacks == 1

    def test_first_creation_commits_one_activity_row(self) -> None:
        session = _create_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=None),
                FakeResult(scalar=POST_ID),
            ]
        )

        post_id, created = create_post(session, actor_id=ACTOR, data=_create_data())

        assert (post_id, created) == (POST_ID, True)
        assert len(session.added) == 1
        activity = session.added[0]
        assert activity.event_type == "created"
        assert activity.post_id == POST_ID and activity.actor_id == ACTOR
        assert session.flushes == 1 and session.commits == 1
        assert session.rollbacks == 0


def _update_session(results: list, **session_kwargs: object) -> RecordingSession:
    session = RecordingSession(results)
    for key, value in session_kwargs.items():
        setattr(session, key, value)
    return session


def _update_data(**overrides: object) -> PostUpdate:
    payload = _fields(expected_version=1, status="idea")
    payload.update(overrides)
    return PostUpdate(**payload)


class TestUpdateUsesAtomicVersion:
    def test_update_uses_atomic_expected_version(self) -> None:
        current = _post()
        updated = _post(title="Rewritten", version=2, content_revision=2, updated_by=ACTOR)
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=current),
                FakeResult(scalar=updated),
            ]
        )

        result = update_post(
            session,
            actor_id=ACTOR,
            post_id=POST_ID,
            data=_update_data(title="Rewritten"),
        )

        assert result.version == 2 and result.content_revision == 2
        assert result.updated_by == ACTOR
        update_sql = session.sql()[2]
        assert update_sql.startswith("UPDATE planner_posts")
        assert re.search(
            r"WHERE planner_posts\.id = .*planner_posts\.version =", update_sql, re.S
        ), update_sql
        assert "planner_posts.archived_at IS NULL" in update_sql
        assert len(session.added) == 1
        assert session.added[0].event_type == "updated"
        assert session.added[0].details["fields"] == ["title"]
        assert session.flushes == 1 and session.commits == 1
        assert session.rollbacks == 0

    def test_metadata_only_update_preserves_content_revision(self) -> None:
        current = _post()
        updated = _post(notes="New note", version=2, content_revision=1, updated_by=ACTOR)
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=current),
                FakeResult(scalar=updated),
            ]
        )

        result = update_post(
            session,
            actor_id=ACTOR,
            post_id=POST_ID,
            data=_update_data(notes="New note"),
        )

        assert result.version == 2 and result.content_revision == 1
        assert session.added[0].details["fields"] == ["notes"]
        assert session.commits == 1

    def test_stale_noop_is_still_conflict(self) -> None:
        current = _post(version=2, title="Same values")
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=current),
                FakeResult(scalar=None),
            ]
        )

        with pytest.raises(PlannerVersionConflictError):
            update_post(
                session,
                actor_id=ACTOR,
                post_id=POST_ID,
                data=_update_data(expected_version=1, title="Same values"),
            )

        assert [statement for statement in session.sql() if statement.startswith("UPDATE")] == []
        assert session.added == []
        assert session.commits == 0
        assert session.rollbacks == 1

    def test_unknown_post_is_404(self) -> None:
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=None),
            ]
        )
        with pytest.raises(PlannerPostNotFoundError):
            update_post(
                session, actor_id=ACTOR, post_id=POST_ID, data=_update_data()
            )
        assert session.rollbacks == 1

    def test_archived_post_edit_is_conflict(self) -> None:
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=_post(archived_at=NOW)),
            ]
        )
        with pytest.raises(PlannerPostArchivedError):
            update_post(
                session, actor_id=ACTOR, post_id=POST_ID, data=_update_data()
            )
        assert session.added == []
        assert session.commits == 0

    def test_stale_version_after_mutation_is_conflict(self) -> None:
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=_post()),
                FakeResult(scalar=None),
                FakeResult(scalar=_post(version=2)),
            ]
        )
        with pytest.raises(PlannerVersionConflictError):
            update_post(
                session,
                actor_id=ACTOR,
                post_id=POST_ID,
                data=_update_data(title="Rewritten"),
            )
        assert session.commits == 0
        assert session.rollbacks == 1


class TestAssignmentRules:
    def test_unknown_assignee_is_rejected(self) -> None:
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=_post()),
            ]
        )
        with pytest.raises(PlannerAssigneeInvalidError):
            update_post(
                session,
                actor_id=ACTOR,
                post_id=POST_ID,
                data=_update_data(assignee_id=OTHER),
            )
        assert session.commits == 0

    def test_inactive_assignee_is_rejected(self) -> None:
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR), _membership(OTHER, active=False)]),
                FakeResult(scalar=_post()),
            ]
        )
        with pytest.raises(PlannerAssigneeInvalidError):
            update_post(
                session,
                actor_id=ACTOR,
                post_id=POST_ID,
                data=_update_data(assignee_id=OTHER),
            )

    def test_unchanged_inactive_assignee_does_not_block_other_edits(self) -> None:
        current = _post(assignee_id=OTHER)
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR), _membership(OTHER, active=False)]),
                FakeResult(scalar=current),
                FakeResult(scalar=_post(assignee_id=OTHER, notes="n", version=2)),
            ]
        )

        result = update_post(
            session,
            actor_id=ACTOR,
            post_id=POST_ID,
            data=_update_data(assignee_id=OTHER, notes="n"),
        )

        assert result.version == 2
        assert session.commits == 1


class TestMembershipRecheckedInsideTransaction:
    def test_membership_rechecked_before_write(self) -> None:
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR, active=False)]),
            ]
        )

        with pytest.raises(AuthInactiveError):
            update_post(
                session, actor_id=ACTOR, post_id=POST_ID, data=_update_data()
            )

        assert len(session.statements) == 1
        assert str(session.statements[0]).startswith("SELECT")
        assert session.added == []
        assert session.commits == 0
        assert session.rollbacks == 1

    def test_unknown_actor_is_rejected_before_write(self) -> None:
        session = _update_session([FakeResult(entities=[])])
        with pytest.raises(AuthNotMemberError):
            update_post(
                session, actor_id=ACTOR, post_id=POST_ID, data=_update_data()
            )
        assert session.commits == 0

    def test_inactive_actor_on_create_is_rejected(self) -> None:
        session = _create_session([FakeResult(entities=[_membership(ACTOR, active=False)])])
        with pytest.raises(AuthInactiveError):
            create_post(session, actor_id=ACTOR, data=_create_data())
        assert len(session.statements) == 1
        assert session.commits == 0


class TestFailureNeverReportsSuccess:
    def test_commit_failure_has_no_success_and_rolls_back(self) -> None:
        current = _post()
        updated = _post(version=2, content_revision=2, updated_by=ACTOR)
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=current),
                FakeResult(scalar=updated),
            ]
        )
        session.commit_error = _db_error()

        with pytest.raises(DataUnavailableError) as excinfo:
            update_post(
                session,
                actor_id=ACTOR,
                post_id=POST_ID,
                data=_update_data(title="Rewritten"),
            )

        assert excinfo.value.message == "planner data is unavailable"
        assert SECRET not in str(excinfo.value)
        assert isinstance(excinfo.value.__cause__, OperationalError)
        assert session.commits == 1
        assert session.rollbacks == 1

    def test_activity_failure_rolls_back_post(self) -> None:
        current = _post()
        updated = _post(version=2, content_revision=2, updated_by=ACTOR)
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=current),
                FakeResult(scalar=updated),
            ]
        )
        session.flush_error = _db_error()

        with pytest.raises(DataUnavailableError) as excinfo:
            update_post(
                session,
                actor_id=ACTOR,
                post_id=POST_ID,
                data=_update_data(title="Rewritten"),
            )

        assert excinfo.value.message == "planner data is unavailable"
        assert SECRET not in str(excinfo.value)
        assert session.commits == 0
        assert session.rollbacks == 1

    def test_create_commit_failure_is_sanitized(self) -> None:
        session = _create_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=None),
                FakeResult(scalar=POST_ID),
            ]
        )
        session.commit_error = _db_error()

        with pytest.raises(DataUnavailableError) as excinfo:
            create_post(session, actor_id=ACTOR, data=_create_data())

        assert SECRET not in str(excinfo.value)
        assert session.rollbacks == 1


class TestArchiveAndRestore:
    def test_archive_updates_state_with_version_predicate(self) -> None:
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=_post()),
                FakeResult(scalar=_post(version=2, archived_at=NOW, updated_by=ACTOR)),
            ]
        )

        result = set_archived(
            session,
            actor_id=ACTOR,
            post_id=POST_ID,
            expected_version=1,
            archived=True,
        )

        assert result.archived_at == NOW and result.version == 2
        update_sql = session.sql()[2]
        assert "planner_posts.archived_at IS NULL" in update_sql
        assert re.search(
            r"WHERE planner_posts\.id = .*planner_posts\.version =", update_sql, re.S
        ), update_sql
        assert session.added[0].event_type == "archived"
        assert session.commits == 1

    def test_restore_uses_archived_predicate(self) -> None:
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=_post(archived_at=NOW, version=3)),
                FakeResult(scalar=_post(version=4, updated_by=ACTOR)),
            ]
        )

        result = set_archived(
            session,
            actor_id=ACTOR,
            post_id=POST_ID,
            expected_version=3,
            archived=False,
        )

        assert result.archived_at is None and result.version == 4
        update_sql = session.sql()[2]
        assert "planner_posts.archived_at IS NOT NULL" in update_sql
        assert session.added[0].event_type == "restored"

    def test_archive_noop_does_not_increment_version(self) -> None:
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=_post(archived_at=NOW)),
                FakeResult(scalar=_post(archived_at=NOW)),
            ]
        )

        result = set_archived(
            session,
            actor_id=ACTOR,
            post_id=POST_ID,
            expected_version=1,
            archived=True,
        )

        assert result.version == 1
        assert session.added == []
        assert session.commits == 0

    def test_stale_archive_is_conflict(self) -> None:
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=_post(version=4, updated_by=ACTOR)),
                FakeResult(scalar=None),
                FakeResult(scalar=_post(version=5)),
            ]
        )

        with pytest.raises(PlannerVersionConflictError):
            set_archived(
                session,
                actor_id=ACTOR,
                post_id=POST_ID,
                expected_version=1,
                archived=True,
            )
        assert session.commits == 0


def _lock_statement(statement) -> str:
    """Render a statement the way the PostgreSQL driver will see it."""
    return str(statement.compile(dialect=postgresql.dialect()))


class TestMemberLockReadsEntities:
    """The lock SELECT is an entity SELECT: read it with ``.scalars()``."""

    def test_lock_returns_entities_and_refreshes_the_identity_map(self) -> None:
        session = RecordingSession(
            [FakeResult(entities=[_membership(ACTOR), _membership(OTHER)])]
        )

        members = _lock_members(session, (ACTOR, OTHER))

        assert set(members) == {ACTOR, OTHER}
        assert members[ACTOR].active is True
        statement = session.statements[0]
        assert statement.get_execution_options().get("populate_existing") is True
        assert "FOR SHARE" in _lock_statement(statement)

    def test_row_only_exposes_the_entity_name(self) -> None:
        row = FakeResult(entities=[_membership(ACTOR)]).all()[0]

        assert row.Membership.user_id == ACTOR
        assert row[0].user_id == ACTOR
        with pytest.raises(AttributeError):
            row.user_id

    @pytest.mark.parametrize("mutation", ["create", "update", "archive"])
    def test_every_mutation_locks_and_refreshes_first(self, mutation: str) -> None:
        if mutation == "create":
            session = RecordingSession(
                [
                    FakeResult(entities=[_membership(ACTOR)]),
                    FakeResult(scalar=None),
                    FakeResult(scalar=POST_ID),
                ]
            )
            create_post(session, actor_id=ACTOR, data=_create_data())
        elif mutation == "update":
            session = RecordingSession(
                [
                    FakeResult(entities=[_membership(ACTOR)]),
                    FakeResult(scalar=_post()),
                    FakeResult(scalar=_post(version=2, updated_by=ACTOR)),
                ]
            )
            update_post(
                session,
                actor_id=ACTOR,
                post_id=POST_ID,
                data=_update_data(title="Rewritten"),
            )
        else:
            session = RecordingSession(
                [
                    FakeResult(entities=[_membership(ACTOR)]),
                    FakeResult(scalar=_post()),
                    FakeResult(scalar=_post(version=2, archived_at=NOW)),
                ]
            )
            set_archived(
                session,
                actor_id=ACTOR,
                post_id=POST_ID,
                expected_version=1,
                archived=True,
            )

        statement = session.statements[0]
        assert statement.get_execution_options().get("populate_existing") is True
        assert "FOR SHARE" in _lock_statement(statement)
        assert session.commits == 1


class TestReplayBeatsLaterMembershipChanges:
    """A committed creation replays even if its assignee is no longer active."""

    def test_replay_after_assignee_deactivation_returns_the_original_id(
        self,
    ) -> None:
        data = _create_data(assignee_id=OTHER)
        stored = _post(assignee_id=OTHER, create_payload_hash=_payload_hash(data))
        session = RecordingSession(
            [
                FakeResult(
                    entities=[_membership(ACTOR), _membership(OTHER, active=False)]
                ),
                FakeResult(scalar=stored),
            ]
        )

        assert create_post(session, actor_id=ACTOR, data=data) == (POST_ID, False)
        assert session.commits == 0
        assert session.added == []

    def test_genuine_creation_still_validates_the_assignee(self) -> None:
        session = RecordingSession(
            [
                FakeResult(
                    entities=[_membership(ACTOR), _membership(OTHER, active=False)]
                ),
                FakeResult(scalar=None),
            ]
        )

        with pytest.raises(PlannerAssigneeInvalidError):
            create_post(
                session, actor_id=ACTOR, data=_create_data(assignee_id=OTHER)
            )
        assert session.commits == 0
        assert session.added == []

    def test_insert_losing_the_race_to_a_winner_replays(self) -> None:
        data = _create_data()
        stored = _post(create_payload_hash=_payload_hash(data))
        session = RecordingSession(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=None),
                FakeResult(scalar=None),
                FakeResult(scalar=stored),
            ]
        )

        assert create_post(session, actor_id=ACTOR, data=data) == (POST_ID, False)
        assert session.commits == 0
        assert session.added == []

    def test_insert_losing_to_a_different_payload_conflicts(self) -> None:
        session = RecordingSession(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=None),
                FakeResult(scalar=None),
                FakeResult(scalar=_post(create_payload_hash="f" * 64)),
            ]
        )

        with pytest.raises(PlannerCreateConflictError):
            create_post(session, actor_id=ACTOR, data=_create_data())
        assert session.commits == 0
        assert session.rollbacks == 1


class TestSnapshotIsSerializedBeforeCommit:
    """Serialize the response before commit: post-commit expiry re-queries."""

    def test_update_serializes_before_commit(self) -> None:
        updated = _post(
            title="Rewritten",
            version=2,
            content_revision=2,
            updated_by=ACTOR,
            asset_links=None,
        )
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=_post()),
                FakeResult(scalar=updated),
            ]
        )

        with pytest.raises(TypeError):
            update_post(
                session,
                actor_id=ACTOR,
                post_id=POST_ID,
                data=_update_data(title="Rewritten"),
            )

        assert session.commits == 0
        assert session.rollbacks == 1

    def test_archive_serializes_before_commit(self) -> None:
        archived = _post(version=2, archived_at=NOW, asset_links=None)
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=_post()),
                FakeResult(scalar=archived),
            ]
        )

        with pytest.raises(TypeError):
            set_archived(
                session,
                actor_id=ACTOR,
                post_id=POST_ID,
                expected_version=1,
                archived=True,
            )

        assert session.commits == 0
        assert session.rollbacks == 1

    def test_archive_commit_failure_reports_no_success(self) -> None:
        session = _update_session(
            [
                FakeResult(entities=[_membership(ACTOR)]),
                FakeResult(scalar=_post()),
                FakeResult(scalar=_post(version=2, archived_at=NOW)),
            ]
        )
        session.commit_error = _db_error()

        with pytest.raises(DataUnavailableError) as excinfo:
            set_archived(
                session,
                actor_id=ACTOR,
                post_id=POST_ID,
                expected_version=1,
                archived=True,
            )

        assert excinfo.value.message == "planner data is unavailable"
        assert SECRET not in str(excinfo.value)
        assert session.commits == 1
        assert session.rollbacks == 1
