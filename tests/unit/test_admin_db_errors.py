"""Gate A: database failures map to a sanitized 503 data_unavailable.

Mocked only: no real database. SQLAlchemy failures in admin reads/writes and
session setup must surface as ``503 data_unavailable`` with a fixed message
(never the driver's, which can embed connection credentials), while
authorization, validation, and invariant errors keep their distinct statuses.
Rollback and the atomic permission history contract stay intact.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from tests.support.app import (
    ADMIN_MEMBER,
    TEST_MEMBER,
    create_test_app,
    membership_row,
)
from trendora.api.admin import apply_member_patch
from trendora.api.app import get_session
from trendora.api.errors import (
    AuthNotMemberError,
    DataUnavailableError,
    LastAdminError,
)

LIST_PATH = "/api/v1/admin/members"
HISTORY_PATH = "/api/v1/admin/members/permission-history"
SECRET = "hunter2-s3cret"
CAUSE = f"connection failed; password={SECRET}"


def _db_error() -> OperationalError:
    return OperationalError("select memberships", {}, Exception(CAUSE))


def _client(session: MagicMock, member=ADMIN_MEMBER) -> TestClient:
    app = create_test_app(member)
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


class TestAdminReadsReturn503:
    def test_list_members_db_failure_is_503_and_sanitized(self) -> None:
        session = MagicMock()
        session.scalars.side_effect = _db_error()
        response = _client(session).get(LIST_PATH)
        assert response.status_code == 503
        body = response.json()["error"]
        assert body["code"] == "data_unavailable"
        assert body["message"] == "membership data is unavailable"
        assert SECRET not in response.text

    def test_permission_history_db_failure_is_503_and_sanitized(self) -> None:
        session = MagicMock()
        session.scalars.side_effect = _db_error()
        response = _client(session).get(HISTORY_PATH)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "data_unavailable"
        assert SECRET not in response.text


class TestAdminWriteReturns503WithRollback:
    def test_patch_db_failure_is_503_and_rolls_back_without_history(self) -> None:
        session = MagicMock()
        session.execute.side_effect = _db_error()
        response = _client(session).patch(
            f"{LIST_PATH}/{ADMIN_MEMBER.user_id}", json={"active": False}
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "data_unavailable"
        assert SECRET not in response.text
        session.rollback.assert_called()
        session.add.assert_not_called()
        session.commit.assert_not_called()

    def test_direct_write_maps_sqlalchemy_error(self) -> None:
        session = MagicMock()
        session.execute.side_effect = _db_error()
        with pytest.raises(DataUnavailableError) as excinfo:
            apply_member_patch(
                session,
                actor_id=ADMIN_MEMBER.user_id,
                subject_id=TEST_MEMBER.user_id,
                changes={"active": False},
            )
        assert isinstance(excinfo.value.__cause__, OperationalError)
        assert SECRET not in str(excinfo.value)
        session.rollback.assert_called_once()
        session.commit.assert_not_called()


class TestAuthorizationAndInvariantStayDistinct:
    def test_missing_actor_stays_403_style_error_and_rolls_back(self) -> None:
        session = MagicMock()
        session.get.return_value = None
        with pytest.raises(AuthNotMemberError):
            apply_member_patch(
                session,
                actor_id=ADMIN_MEMBER.user_id,
                subject_id=TEST_MEMBER.user_id,
                changes={"active": False},
            )
        session.rollback.assert_called_once()
        session.commit.assert_not_called()

    def test_last_admin_stays_409_style_error_and_rolls_back(self) -> None:
        actor = membership_row(ADMIN_MEMBER.user_id, is_admin=True)
        subject = membership_row(TEST_MEMBER.user_id, active=True)
        session = MagicMock()
        session.get.side_effect = [actor, subject]
        session.scalar.return_value = 0
        with pytest.raises(LastAdminError):
            apply_member_patch(
                session,
                actor_id=ADMIN_MEMBER.user_id,
                subject_id=TEST_MEMBER.user_id,
                changes={"active": False},
            )
        session.rollback.assert_called_once()
        session.add.assert_not_called()
        session.commit.assert_not_called()

    def test_validation_error_stays_422(self) -> None:
        app = create_test_app(ADMIN_MEMBER)
        app.dependency_overrides[get_session] = lambda: MagicMock()
        response = TestClient(app).patch(
            f"{LIST_PATH}/{ADMIN_MEMBER.user_id}", json={"unknown_flag": True}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"

    def test_non_admin_stays_403(self) -> None:
        app = create_test_app(TEST_MEMBER)
        app.dependency_overrides[get_session] = lambda: MagicMock()
        response = TestClient(app).patch(
            f"{LIST_PATH}/{TEST_MEMBER.user_id}", json={"active": False}
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "auth_forbidden_admin"


class TestSessionSetupFailure:
    def test_factory_failure_is_503_and_sanitized(self, monkeypatch) -> None:
        def boom():
            raise _db_error()

        monkeypatch.setattr("trendora.api.deps.get_session_factory", boom)
        app = create_test_app(ADMIN_MEMBER)
        response = TestClient(app).get(LIST_PATH)
        assert response.status_code == 503
        body = response.json()["error"]
        assert body["code"] == "data_unavailable"
        assert body["message"] == "database session unavailable"
        assert SECRET not in response.text
