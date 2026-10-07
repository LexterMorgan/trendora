"""Gate A: HTTP mapping of the auth dependency chain (mocked claims/JWKS)."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from tests.support.app import ADMIN_MEMBER, TEST_MEMBER, FakeSession, membership_row
from tests.unit.test_auth_verifier import _structural_token
from trendora.api.app import create_app, get_session
from trendora.api.auth import VerifiedClaims, get_verified_claims

PROTECTED = "/api/v1/research/reports"
SUPABASE_URL = "https://example.supabase.co"


def _raw_client() -> TestClient:
    """App with no auth overrides; the session dependency is stubbed so a
    request never builds the application engine."""
    app = create_app()
    app.dependency_overrides[get_session] = lambda: FakeSession()
    return TestClient(app)


def _claims(sub: str | None = None, role: str = "authenticated") -> VerifiedClaims:
    return VerifiedClaims(sub=sub or str(TEST_MEMBER.user_id), role=role)


def _app_with_claims(claims: VerifiedClaims, session: FakeSession) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_verified_claims] = lambda: claims
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


class TestMissingCredentials:
    def test_no_authorization_header_is_401(self) -> None:
        response = _raw_client().get(PROTECTED)
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["code"] == "auth_missing"
        assert response.headers["WWW-Authenticate"].lower().startswith("bearer")

    def test_non_bearer_scheme_is_401(self) -> None:
        response = _raw_client().get(
            PROTECTED, headers={"Authorization": "Basic dXNlcjpwYXNz"}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "auth_missing"

    def test_empty_bearer_token_is_401(self) -> None:
        response = _raw_client().get(
            PROTECTED, headers={"Authorization": "Bearer   "}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "auth_missing"

    def test_admin_route_without_token_is_401(self) -> None:
        response = _raw_client().get("/api/v1/admin/members")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "auth_missing"


class TestUnavailableAuth:
    def test_missing_supabase_url_is_503(self, supabase_env) -> None:
        supabase_env(None)
        response = _raw_client().get(
            PROTECTED, headers={"Authorization": "Bearer a.b.c"}
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "auth_unavailable"

    def test_jwks_fetch_failure_is_503(
        self, supabase_env, monkeypatch
    ) -> None:
        supabase_env(SUPABASE_URL)

        def boom() -> dict:
            raise httpx.ConnectError("jwks unreachable")

        monkeypatch.setattr("trendora.api.auth.get_jwks", boom)
        response = _raw_client().get(
            PROTECTED, headers={"Authorization": f"Bearer {_structural_token()}"}
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "auth_unavailable"

    def test_member_loader_db_failure_is_503(self) -> None:
        client = _app_with_claims(
            _claims(), FakeSession(error=SQLAlchemyError("connection lost"))
        )
        response = client.get(PROTECTED, headers={"Authorization": "Bearer a.b.c"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "data_unavailable"


class TestClaimAndMembershipFailures:
    def test_undecodable_token_is_401(self, supabase_env, monkeypatch) -> None:
        supabase_env(SUPABASE_URL)
        monkeypatch.setattr("trendora.api.auth.get_jwks", lambda: {"keys": []})
        response = _raw_client().get(
            PROTECTED, headers={"Authorization": "Bearer a.b.c"}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "auth_invalid_token"

    def test_non_uuid_subject_is_401(self) -> None:
        client = _app_with_claims(_claims(sub="not-a-uuid"), FakeSession())
        response = client.get(PROTECTED, headers={"Authorization": "Bearer a.b.c"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "auth_invalid_token"

    def test_unknown_member_is_403(self) -> None:
        client = _app_with_claims(_claims(), FakeSession(row=None))
        response = client.get(PROTECTED, headers={"Authorization": "Bearer a.b.c"})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "auth_not_member"

    def test_inactive_member_is_403(self) -> None:
        row = membership_row(TEST_MEMBER.user_id, active=False)
        client = _app_with_claims(_claims(), FakeSession(row=row))
        response = client.get(PROTECTED, headers={"Authorization": "Bearer a.b.c"})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "auth_inactive"


class TestAuthenticatedRequests:
    def test_active_member_reaches_handler(self, monkeypatch) -> None:
        captured: dict = {}

        def fake_records(session, *, limit=50, offset=0, visible_from=None):
            captured.update(limit=limit, offset=offset, visible_from=visible_from)
            return [], 0

        monkeypatch.setattr(
            "trendora.research.repository.get_report_records", fake_records
        )
        client = _app_with_claims(
            _claims(), FakeSession(row=membership_row(TEST_MEMBER.user_id))
        )
        response = client.get(
            PROTECTED, headers={"Authorization": "Bearer a.b.c"}
        )
        assert response.status_code == 200
        assert response.json() == []
        assert captured["limit"] == 50 and captured["offset"] == 0

    def test_health_is_public(self) -> None:
        response = _raw_client().get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_admin_member_accepted_on_admin_route(self, monkeypatch) -> None:
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
        client = _app_with_claims(
            _claims(sub=str(ADMIN_MEMBER.user_id)),
            FakeSession(row=membership_row(ADMIN_MEMBER.user_id, is_admin=True)),
        )
        response = client.get(
            "/api/v1/admin/members", headers={"Authorization": "Bearer a.b.c"}
        )
        assert response.status_code == 200
        assert response.json()[0]["email"] == ADMIN_MEMBER.email


class TestProductionGuard:
    def test_production_without_supabase_url_refuses_to_start(
        self, supabase_env
    ) -> None:
        supabase_env(None, app_env="production")
        with pytest.raises(RuntimeError, match="SUPABASE_URL"):
            create_app()

    def test_production_with_supabase_url_starts(self, supabase_env) -> None:
        supabase_env(SUPABASE_URL, app_env="production")
        assert create_app() is not None

    def test_development_without_supabase_url_starts(self, supabase_env) -> None:
        supabase_env(None, app_env="development")
        assert create_app() is not None
