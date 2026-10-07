"""Real-transaction planner checks (P2A Task 2). Approved target only.

Every committed write runs through ``approved_engine`` and nothing else: the
fixture TRUNCATEs planner and membership rows on that approved target before
and after each test. These checks prove what mocks cannot: concurrent
creation collapses to one row, competing version-1 saves produce exactly one
winner, an activity failure leaves no partial post, and a membership change
racing an assignment resolves to the committed membership state.

Real race execution, upgrade/downgrade, and role-state coverage stay pending
explicit disposable-cluster approval and main-reviewer inspection.
"""

from __future__ import annotations

import threading
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from trendora.api.admin import apply_member_patch
from trendora.api.errors import DataUnavailableError
from trendora.models.membership import Membership
from trendora.models.planner import PlannerPost, PlannerPostActivity
from trendora.planner import (
    PlannerAssigneeInvalidError,
    PlannerCreateConflictError,
    PlannerVersionConflictError,
    PostCreate,
    PostUpdate,
    create_post,
    set_archived,
    update_post,
)

pytestmark = pytest.mark.integration

ACTOR = UUID("00000000-0000-4000-8000-0000000000b1")
ASSIGNEE = UUID("00000000-0000-4000-8000-0000000000b2")
WIPE = (
    "TRUNCATE planner_post_activity, planner_post_origin_sources, planner_posts, "
    "membership_permission_history, memberships"
)


@pytest.fixture
def planner_rows(approved_engine):
    def wipe() -> None:
        with Session(approved_engine) as session:
            session.execute(text(WIPE))
            session.commit()

    wipe()
    yield
    wipe()


def _seed_members(session: Session) -> None:
    session.add(Membership(user_id=ACTOR, email="actor@example.com", is_admin=True))
    session.add(Membership(user_id=ASSIGNEE, email="assignee@example.com"))
    session.commit()


def _payload(request_id: UUID, **overrides: object) -> PostCreate:
    fields: dict[str, object] = {
        "request_id": request_id,
        "title": "Shared draft",
        "platform": "Instagram",
        "caption": "Caption text",
        "hook": "Hook line",
        "creative_brief": "Studio brief",
        "asset_links": ["https://example.com/asset"],
        "notes": "Internal note",
        "planned_date": None,
        "assignee_id": None,
    }
    fields.update(overrides)
    return PostCreate(**fields)


def _update(expected_version: int, **overrides: object) -> PostUpdate:
    fields: dict[str, object] = {
        "expected_version": expected_version,
        "status": "idea",
        "title": "Shared draft",
        "platform": "Instagram",
        "caption": "Caption text",
        "hook": "Hook line",
        "creative_brief": "Studio brief",
        "asset_links": ["https://example.com/asset"],
        "notes": "Internal note",
        "planned_date": None,
        "assignee_id": None,
    }
    fields.update(overrides)
    return PostUpdate(**fields)


def _run_many(workers: list) -> list[BaseException]:
    """Start every worker, join with a bound, and return their failures."""
    errors: list[BaseException] = []

    def wrap(worker) -> threading.Thread:
        def target() -> None:
            try:
                worker()
            except BaseException as exc:  # noqa: BLE001 - asserted by the caller
                errors.append(exc)

        return threading.Thread(target=target, daemon=True)

    threads = [wrap(worker) for worker in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    assert all(not thread.is_alive() for thread in threads), "worker never finished"
    return errors


class TestConcurrentCreation:
    def test_identical_concurrent_creation_yields_one_post(
        self, approved_engine, planner_rows
    ) -> None:
        with Session(approved_engine) as session:
            _seed_members(session)
        request_id = uuid4()
        ready = threading.Barrier(2, timeout=15)
        results: list[tuple[UUID, bool]] = []
        lock = threading.Lock()

        def worker() -> None:
            with Session(approved_engine) as session:
                ready.wait()
                outcome = create_post(
                    session, actor_id=ACTOR, data=_payload(request_id)
                )
            with lock:
                results.append(outcome)

        errors = _run_many([worker, worker])

        assert errors == [], f"worker failed: {errors}"
        assert len(results) == 2
        assert results[0][0] == results[1][0]
        assert sorted(created for _, created in results) == [False, True]
        with Session(approved_engine) as session:
            assert session.query(PlannerPost).count() == 1
            assert session.query(PlannerPostActivity).count() == 1

    def test_changed_payload_sharing_a_key_conflicts(
        self, approved_engine, planner_rows
    ) -> None:
        with Session(approved_engine) as session:
            _seed_members(session)
        request_id = uuid4()
        with Session(approved_engine) as session:
            post_id, created = create_post(
                session, actor_id=ACTOR, data=_payload(request_id)
            )
        assert created is True

        with Session(approved_engine) as session:
            with pytest.raises(PlannerCreateConflictError):
                create_post(
                    session,
                    actor_id=ACTOR,
                    data=_payload(request_id, title="A different title"),
                )

        with Session(approved_engine) as session:
            assert session.query(PlannerPost).count() == 1
            assert session.query(PlannerPostActivity).count() == 1
            assert session.get(PlannerPost, post_id).title == "Shared draft"


class TestConcurrentVersionOneSaves:
    def test_one_winner_one_conflict_and_no_loser_activity(
        self, approved_engine, planner_rows
    ) -> None:
        with Session(approved_engine) as session:
            _seed_members(session)
            post_id, _ = create_post(session, actor_id=ACTOR, data=_payload(uuid4()))

        ready = threading.Barrier(2, timeout=15)
        outcomes: dict[str, str] = {}
        lock = threading.Lock()

        def worker(label: str, title: str) -> None:
            with Session(approved_engine) as session:
                ready.wait()
                try:
                    update_post(
                        session,
                        actor_id=ACTOR,
                        post_id=post_id,
                        data=_update(1, title=title),
                    )
                    result = "updated"
                except PlannerVersionConflictError:
                    result = "conflict"
            with lock:
                outcomes[label] = result

        errors = _run_many(
            [
                lambda: worker("a", "Winner A"),
                lambda: worker("b", "Winner B"),
            ]
        )
        assert len(outcomes) == 2, f"workers failed: {errors}"
        assert sorted(outcomes.values()) == ["conflict", "updated"]

        with Session(approved_engine) as session:
            row = session.get(PlannerPost, post_id)
            assert row.version == 2
            assert row.title in ("Winner A", "Winner B")
            assert row.content_revision == 2
            events = [
                event_type for (event_type,) in session.query(
                    PlannerPostActivity.event_type
                ).all()
            ]
            assert sorted(events) == ["created", "updated"]


class TestActivityFailureIsAtomic:
    def test_blocked_activity_insert_leaves_no_partial_post(
        self, approved_engine, planner_rows
    ) -> None:
        with Session(approved_engine) as session:
            _seed_members(session)
            request_id = uuid4()

        def block_activity(mapper, connection, target) -> None:
            raise OperationalError(
                "insert planner_post_activity", {}, Exception("blocked")
            )

        event.listen(PlannerPostActivity, "before_insert", block_activity)
        try:
            with Session(approved_engine) as session:
                with pytest.raises(DataUnavailableError) as excinfo:
                    create_post(session, actor_id=ACTOR, data=_payload(request_id))
        finally:
            event.remove(PlannerPostActivity, "before_insert", block_activity)

        assert excinfo.value.message == "planner data is unavailable"
        with Session(approved_engine) as session:
            assert session.query(PlannerPost).count() == 0
            assert session.query(PlannerPostActivity).count() == 0


class TestMembershipCoordination:
    def test_deactivation_racing_a_new_assignment_never_wins(
        self, approved_engine, planner_rows
    ) -> None:
        with Session(approved_engine) as session:
            _seed_members(session)
            post_id, _ = create_post(session, actor_id=ACTOR, data=_payload(uuid4()))

        locked = threading.Event()
        release = threading.Event()
        holder_errors: list[BaseException] = []

        def holder() -> None:
            try:
                with Session(approved_engine) as session:
                    session.execute(text("LOCK TABLE memberships IN EXCLUSIVE MODE"))
                    locked.set()
                    if not release.wait(15):
                        raise TimeoutError("release was never signalled")
                    apply_member_patch(
                        session,
                        actor_id=ACTOR,
                        subject_id=ASSIGNEE,
                        changes={"active": False},
                    )
            except BaseException as exc:  # noqa: BLE001 - asserted below
                holder_errors.append(exc)
                locked.set()
                release.set()

        holder_thread = threading.Thread(target=holder, daemon=True)
        holder_thread.start()
        assert locked.wait(15), "membership holder never started"
        if holder_errors:
            pytest.fail(f"membership holder failed: {holder_errors[0]}")

        worker_errors: list[BaseException] = []

        def worker() -> None:
            try:
                with Session(approved_engine) as session:
                    update_post(
                        session,
                        actor_id=ACTOR,
                        post_id=post_id,
                        data=_update(1, assignee_id=ASSIGNEE),
                    )
            except BaseException as exc:  # noqa: BLE001 - asserted below
                worker_errors.append(exc)

        worker_thread = threading.Thread(target=worker, daemon=True)
        worker_thread.start()
        worker_thread.join(1)
        assert worker_thread.is_alive(), (
            "the assignment must stay blocked while the membership lock is held"
        )
        release.set()
        worker_thread.join(15)
        holder_thread.join(15)
        assert not worker_thread.is_alive() and not holder_thread.is_alive()
        assert holder_errors == []
        assert len(worker_errors) == 1
        assert isinstance(worker_errors[0], PlannerAssigneeInvalidError)

        with Session(approved_engine) as session:
            row = session.get(PlannerPost, post_id)
            assert row.version == 1
            assert row.assignee_id is None
            assert session.query(PlannerPostActivity).count() == 1
            assert session.get(Membership, ASSIGNEE).active is False


class TestRetryAndRevisionRules:
    def test_edited_and_archived_creation_retries_keep_current_content(
        self, approved_engine, planner_rows
    ) -> None:
        with Session(approved_engine) as session:
            _seed_members(session)
        request_id = uuid4()
        with Session(approved_engine) as session:
            post_id, _ = create_post(
                session, actor_id=ACTOR, data=_payload(request_id)
            )
        with Session(approved_engine) as session:
            update_post(
                session,
                actor_id=ACTOR,
                post_id=post_id,
                data=_update(1, title="Edited after creation"),
            )

        with Session(approved_engine) as session:
            replayed_id, created = create_post(
                session, actor_id=ACTOR, data=_payload(request_id)
            )
        assert (replayed_id, created) == (post_id, False)

        with Session(approved_engine) as session:
            set_archived(
                session,
                actor_id=ACTOR,
                post_id=post_id,
                expected_version=2,
                archived=True,
            )
        with Session(approved_engine) as session:
            replayed_id, created = create_post(
                session, actor_id=ACTOR, data=_payload(request_id)
            )
        assert (replayed_id, created) == (post_id, False)

        with Session(approved_engine) as session:
            row = session.get(PlannerPost, post_id)
            assert row.title == "Edited after creation"
            assert row.version == 3
            assert row.archived_at is not None
            assert row.content_revision == 2
            assert session.query(PlannerPostActivity).count() == 3

    def test_metadata_only_change_preserves_content_revision(
        self, approved_engine, planner_rows
    ) -> None:
        with Session(approved_engine) as session:
            _seed_members(session)
            post_id, _ = create_post(session, actor_id=ACTOR, data=_payload(uuid4()))
        with Session(approved_engine) as session:
            update_post(
                session,
                actor_id=ACTOR,
                post_id=post_id,
                data=_update(1, notes="Rewritten note"),
            )
        with Session(approved_engine) as session:
            update_post(
                session,
                actor_id=ACTOR,
                post_id=post_id,
                data=_update(2, title="New title", notes="Rewritten note"),
            )

        with Session(approved_engine) as session:
            row = session.get(PlannerPost, post_id)
            assert row.version == 3
            assert row.content_revision == 2
            assert row.notes == "Rewritten note"
            assert row.title == "New title"
            details = [
                activity.details
                for activity in session.query(PlannerPostActivity)
                .where(PlannerPostActivity.event_type == "updated")
                .all()
            ]
            observed = sorted(tuple(sorted(entry["fields"])) for entry in details)
            assert observed == [("notes",), ("title",)]

    def test_unsent_field_falls_back_to_the_payload_default(
        self, approved_engine, planner_rows
    ) -> None:
        """A PUT is a full snapshot, not a merge. The helper sends every
        field, so a caller that does not override ``notes`` sends the
        default and replaces the stored text with it; the title change is
        what bumps ``content_revision``."""
        with Session(approved_engine) as session:
            _seed_members(session)
            post_id, _ = create_post(session, actor_id=ACTOR, data=_payload(uuid4()))
        with Session(approved_engine) as session:
            update_post(
                session,
                actor_id=ACTOR,
                post_id=post_id,
                data=_update(1, notes="Rewritten note"),
            )
        with Session(approved_engine) as session:
            update_post(
                session,
                actor_id=ACTOR,
                post_id=post_id,
                data=_update(2, title="New title"),
            )

        with Session(approved_engine) as session:
            row = session.get(PlannerPost, post_id)
            assert row.title == "New title"
            assert row.notes == "Internal note"
            assert row.content_revision == 2
