"""Gate A: ``apply_member_patch`` against real PostgreSQL (scratch schema).

Covers the serialization lock, re-authorization under that lock, the
last-admin invariant, atomic permission history, and rollback on rejection.
"""

from __future__ import annotations

import threading
import time
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from trendora.api.admin import apply_member_patch
from trendora.api.errors import (
    AuthForbiddenAdminError,
    AuthInactiveError,
    AuthNotMemberError,
    LastAdminError,
    MemberNotFoundError,
)
from trendora.models.membership import Membership, MembershipPermissionHistory

ACTOR = UUID("00000000-0000-4000-8000-0000000000a0")
OTHER_ADMIN = UUID("00000000-0000-4000-8000-0000000000a1")
SUBJECT = UUID("00000000-0000-4000-8000-0000000000b0")


@pytest.fixture
def memberships(approved_engine):
    def wipe() -> None:
        with Session(approved_engine) as session:
            session.execute(
                text(
                    "TRUNCATE planner_post_activity, planner_post_origin_sources, planner_posts, "
                    "membership_permission_history, memberships"
                )
            )
            session.commit()

    wipe()
    yield
    wipe()


def _seed(session: Session, user_id: UUID, email: str, **flags: bool) -> None:
    session.add(
        Membership(
            user_id=user_id,
            email=email,
            active=flags.get("active", True),
            is_admin=flags.get("is_admin", False),
            can_approve=flags.get("can_approve", False),
        )
    )
    session.commit()


class TestSuccessfulPatch:
    def test_demote_writes_atomic_history(self, memberships, approved_engine) -> None:
        with Session(approved_engine) as session:
            _seed(session, ACTOR, "actor@example.com", is_admin=True)
            _seed(session, SUBJECT, "subject@example.com", is_admin=True)

        with Session(approved_engine) as session:
            member = apply_member_patch(
                session,
                actor_id=ACTOR,
                subject_id=SUBJECT,
                changes={"is_admin": False},
            )
        assert member.is_admin is False
        assert member.email == "subject@example.com"

        with Session(approved_engine) as session:
            subject = session.get(Membership, SUBJECT)
            assert subject.is_admin is False
            rows = session.query(MembershipPermissionHistory).all()
            assert len(rows) == 1
            assert rows[0].actor_id == ACTOR
            assert rows[0].subject_id == SUBJECT
            assert rows[0].before == {"is_admin": True}
            assert rows[0].after == {"is_admin": False}

    def test_noop_patch_writes_no_history(self, memberships, approved_engine) -> None:
        with Session(approved_engine) as session:
            _seed(session, ACTOR, "actor@example.com", is_admin=True)
            _seed(session, SUBJECT, "subject@example.com", is_admin=True)

        with Session(approved_engine) as session:
            apply_member_patch(
                session,
                actor_id=ACTOR,
                subject_id=SUBJECT,
                changes={"is_admin": True},
            )

        with Session(approved_engine) as session:
            assert session.query(MembershipPermissionHistory).count() == 0


class TestLastAdminInvariant:
    def test_single_admin_cannot_demote_self(
        self, memberships, approved_engine
    ) -> None:
        with Session(approved_engine) as session:
            _seed(session, ACTOR, "actor@example.com", is_admin=True)

        with Session(approved_engine) as session:
            with pytest.raises(LastAdminError):
                apply_member_patch(
                    session,
                    actor_id=ACTOR,
                    subject_id=ACTOR,
                    changes={"is_admin": False},
                )

        with Session(approved_engine) as session:
            assert session.get(Membership, ACTOR).is_admin is True
            assert session.query(MembershipPermissionHistory).count() == 0

    def test_second_admin_demotion_rejected_after_first_succeeds(
        self, memberships, approved_engine
    ) -> None:
        with Session(approved_engine) as session:
            _seed(session, ACTOR, "actor@example.com", is_admin=True)
            _seed(session, OTHER_ADMIN, "other@example.com", is_admin=True)

        with Session(approved_engine) as session:
            apply_member_patch(
                session,
                actor_id=ACTOR,
                subject_id=OTHER_ADMIN,
                changes={"is_admin": False},
            )

        with Session(approved_engine) as session:
            with pytest.raises(LastAdminError):
                apply_member_patch(
                    session,
                    actor_id=ACTOR,
                    subject_id=ACTOR,
                    changes={"is_admin": False},
                )

        with Session(approved_engine) as session:
            assert session.get(Membership, ACTOR).is_admin is True
            assert session.get(Membership, OTHER_ADMIN).is_admin is False
            assert session.query(MembershipPermissionHistory).count() == 1


class TestActorAuthorization:
    def test_inactive_actor_is_rejected(self, memberships, approved_engine) -> None:
        with Session(approved_engine) as session:
            _seed(session, ACTOR, "actor@example.com", is_admin=True, active=False)
            _seed(session, SUBJECT, "subject@example.com")

        with Session(approved_engine) as session:
            with pytest.raises(AuthInactiveError):
                apply_member_patch(
                    session,
                    actor_id=ACTOR,
                    subject_id=SUBJECT,
                    changes={"active": False},
                )

        with Session(approved_engine) as session:
            assert session.get(Membership, SUBJECT).active is True
            assert session.query(MembershipPermissionHistory).count() == 0

    def test_non_admin_actor_is_rejected(self, memberships, approved_engine) -> None:
        with Session(approved_engine) as session:
            _seed(session, ACTOR, "actor@example.com")
            _seed(session, SUBJECT, "subject@example.com")

        with Session(approved_engine) as session:
            with pytest.raises(AuthForbiddenAdminError):
                apply_member_patch(
                    session,
                    actor_id=ACTOR,
                    subject_id=SUBJECT,
                    changes={"active": False},
                )

        with Session(approved_engine) as session:
            assert session.get(Membership, SUBJECT).active is True

    def test_unknown_actor_is_rejected(self, memberships, approved_engine) -> None:
        with Session(approved_engine) as session:
            _seed(session, SUBJECT, "subject@example.com")

        with Session(approved_engine) as session:
            with pytest.raises(AuthNotMemberError):
                apply_member_patch(
                    session,
                    actor_id=uuid4(),
                    subject_id=SUBJECT,
                    changes={"active": False},
                )

    def test_unknown_subject_is_404(self, memberships, approved_engine) -> None:
        with Session(approved_engine) as session:
            _seed(session, ACTOR, "actor@example.com", is_admin=True)

        with Session(approved_engine) as session:
            with pytest.raises(MemberNotFoundError):
                apply_member_patch(
                    session,
                    actor_id=ACTOR,
                    subject_id=uuid4(),
                    changes={"active": False},
                )

        with Session(approved_engine) as session:
            assert session.query(MembershipPermissionHistory).count() == 0

    def test_self_vs_other_race_never_removes_last_admin(
        self, memberships, approved_engine
    ) -> None:
        with Session(approved_engine) as session:
            _seed(session, ACTOR, "actor@example.com", is_admin=True)
            _seed(session, OTHER_ADMIN, "other@example.com", is_admin=True)

        with Session(approved_engine) as session:
            apply_member_patch(
                session,
                actor_id=ACTOR,
                subject_id=OTHER_ADMIN,
                changes={"is_admin": False},
            )

        with Session(approved_engine) as session:
            with pytest.raises(
                (AuthForbiddenAdminError, LastAdminError)
            ):
                apply_member_patch(
                    session,
                    actor_id=OTHER_ADMIN,
                    subject_id=ACTOR,
                    changes={"is_admin": False},
                )

        with Session(approved_engine) as session:
            assert session.get(Membership, ACTOR).is_admin is True
            assert session.query(MembershipPermissionHistory).count() == 1


class TestSerializationLock:
    def test_actor_revocation_committed_under_lock_wins(
        self, memberships, approved_engine
    ) -> None:
        with Session(approved_engine) as session:
            _seed(session, ACTOR, "actor@example.com", is_admin=True)
            _seed(session, OTHER_ADMIN, "other@example.com", is_admin=True)
            _seed(session, SUBJECT, "subject@example.com")

        lock_held = threading.Event()
        release = threading.Event()
        holder_errors: list[BaseException] = []

        def holder() -> None:
            try:
                with Session(approved_engine) as session:
                    session.execute(
                        text("LOCK TABLE memberships IN EXCLUSIVE MODE")
                    )
                    session.execute(
                        text("UPDATE memberships SET active = false WHERE user_id = :u"),
                        {"u": ACTOR},
                    )
                    lock_held.set()
                    if not release.wait(10):
                        raise TimeoutError("release was never signaled")
                    session.commit()
            except BaseException as exc:  # noqa: BLE001 - surfaced to the test
                holder_errors.append(exc)
                lock_held.set()
                release.set()

        holder_thread = threading.Thread(target=holder, daemon=True)
        holder_thread.start()
        assert lock_held.wait(10), "holder never acquired the lock"
        if holder_errors:
            pytest.fail(f"lock holder failed before the test ran: {holder_errors[0]}")

        outcome: dict[str, object] = {}
        started = threading.Event()

        def worker() -> None:
            started.set()
            with Session(approved_engine) as session:
                try:
                    apply_member_patch(
                        session,
                        actor_id=ACTOR,
                        subject_id=SUBJECT,
                        changes={"active": False},
                    )
                    outcome["result"] = "applied"
                except BaseException as exc:  # noqa: BLE001 - asserted below
                    outcome["error"] = exc

        worker_thread = threading.Thread(target=worker, daemon=True)
        worker_thread.start()
        assert started.wait(10), "worker never started"
        time.sleep(0.5)
        assert worker_thread.is_alive(), (
            "apply_member_patch finished while the serialization lock was held"
        )
        release.set()
        worker_thread.join(10)
        holder_thread.join(10)
        assert not worker_thread.is_alive()
        assert not holder_thread.is_alive()
        assert holder_errors == []
        assert isinstance(outcome.get("error"), AuthInactiveError)

        with Session(approved_engine) as session:
            assert session.get(Membership, ACTOR).active is False
            assert session.get(Membership, SUBJECT).active is True
            assert session.query(MembershipPermissionHistory).count() == 0
