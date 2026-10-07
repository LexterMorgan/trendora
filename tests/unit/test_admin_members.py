"""Gate A: admin membership API: authority, validation, and wiring."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.support.app import ADMIN_MEMBER, TEST_MEMBER, FakeSession, create_test_app
from trendora.api.app import create_app, get_session
from trendora.api.auth import Member
from trendora.api.errors import MemberNotFoundError

LIST_PATH = "/api/v1/admin/members"
HISTORY_PATH = "/api/v1/admin/members/permission-history"


def _admin_client() -> TestClient:
    app = create_test_app(ADMIN_MEMBER)
    app.dependency_overrides[get_session] = lambda: FakeSession()
    return TestClient(app)


def _client_without_auth() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: FakeSession()
    return TestClient(app)


class TestAuthority:
    def test_anonymous_request_is_401(self) -> None:
        response = _client_without_auth().get(LIST_PATH)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "auth_missing"

    def test_non_admin_is_403(self) -> None:
        app = create_test_app(TEST_MEMBER)
        app.dependency_overrides[get_session] = lambda: FakeSession()
        response = TestClient(app).get(LIST_PATH)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "auth_forbidden_admin"

    def test_non_admin_cannot_patch(self) -> None:
        app = create_test_app(TEST_MEMBER)
        app.dependency_overrides[get_session] = lambda: FakeSession()
        response = TestClient(app).patch(
            f"{LIST_PATH}/{TEST_MEMBER.user_id}", json={"is_admin": True}
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "auth_forbidden_admin"

    def test_history_route_requires_admin(self) -> None:
        app = create_test_app(TEST_MEMBER)
        app.dependency_overrides[get_session] = lambda: FakeSession()
        response = TestClient(app).get(HISTORY_PATH)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "auth_forbidden_admin"


class TestListEndpoints:
    def test_admin_list_returns_members(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "trendora.api.admin.list_members",
            lambda session: [
                {
                    "user_id": str(ADMIN_MEMBER.user_id),
                    "email": ADMIN_MEMBER.email,
                    "active": True,
                    "is_admin": True,
                    "can_approve": False,
                }
            ],
        )
        response = _admin_client().get(LIST_PATH)
        assert response.status_code == 200
        body = response.json()
        assert body[0]["user_id"] == str(ADMIN_MEMBER.user_id)
        assert body[0]["email"] == ADMIN_MEMBER.email

    def test_admin_history_returns_rows(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "trendora.api.admin.list_permission_history",
            lambda session, *, limit=100, offset=0: [
                {
                    "id": 7,
                    "actor_id": str(ADMIN_MEMBER.user_id),
                    "subject_id": str(TEST_MEMBER.user_id),
                    "before": {"is_admin": False},
                    "after": {"is_admin": True},
                    "created_at": "2026-09-29T00:00:00+00:00",
                }
            ],
        )
        response = _admin_client().get(HISTORY_PATH)
        assert response.status_code == 200
        row = response.json()[0]
        assert row["id"] == 7
        assert row["after"] == {"is_admin": True}


class TestPatchValidation:
    def test_unknown_field_is_422(self) -> None:
        response = _admin_client().patch(
            f"{LIST_PATH}/{TEST_MEMBER.user_id}", json={"is_approver": True}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"

    def test_wrong_type_is_422(self) -> None:
        response = _admin_client().patch(
            f"{LIST_PATH}/{TEST_MEMBER.user_id}", json={"is_admin": "yes"}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"

    def test_invalid_path_uuid_is_422(self) -> None:
        response = _admin_client().patch(
            f"{LIST_PATH}/not-a-uuid", json={"is_admin": True}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"

    def test_patch_without_token_is_401(self) -> None:
        response = _client_without_auth().patch(
            f"{LIST_PATH}/{TEST_MEMBER.user_id}", json={"is_admin": True}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "auth_missing"


class TestPatchWiring:
    def test_patch_passes_actor_subject_and_changes(self, monkeypatch) -> None:
        captured: dict = {}

        def fake_apply(session, *, actor_id, subject_id, changes):
            captured.update(
                actor_id=actor_id, subject_id=subject_id, changes=dict(changes)
            )
            return Member(
                user_id=subject_id,
                email="subject@example.com",
                active=False,
                is_admin=True,
                can_approve=False,
            )

        monkeypatch.setattr("trendora.api.admin.apply_member_patch", fake_apply)
        target = uuid4()
        response = _admin_client().patch(
            f"{LIST_PATH}/{target}", json={"active": False}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["active"] is False
        assert body["email"] == "subject@example.com"
        assert captured == {
            "actor_id": ADMIN_MEMBER.user_id,
            "subject_id": target,
            "changes": {"active": False},
        }

    def test_empty_patch_is_noop_wiring(self, monkeypatch) -> None:
        captured: dict = {}

        def fake_apply(session, *, actor_id, subject_id, changes):
            captured["changes"] = dict(changes)
            return Member(
                user_id=subject_id,
                email="subject@example.com",
                active=True,
                is_admin=True,
                can_approve=False,
            )

        monkeypatch.setattr("trendora.api.admin.apply_member_patch", fake_apply)
        response = _admin_client().patch(
            f"{LIST_PATH}/{uuid4()}", json={}
        )
        assert response.status_code == 200
        assert captured["changes"] == {}

    def test_not_found_maps_to_404(self, monkeypatch) -> None:
        def fake_apply(session, *, actor_id, subject_id, changes):
            raise MemberNotFoundError("no such member")

        monkeypatch.setattr("trendora.api.admin.apply_member_patch", fake_apply)
        response = _admin_client().patch(
            f"{LIST_PATH}/{uuid4()}", json={"active": True}
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "member_not_found"
