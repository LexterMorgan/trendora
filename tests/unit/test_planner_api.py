"""Offline planner API regressions (P2A Task 3).

Mocked sessions and services only: no database, no network, no AI or research
provider. These pin the HTTP contract before wiring: every planner route
fails closed without verified auth, identity always comes from the dependency,
schema rejection keeps the fixed 422 envelope, conflicts and failures keep
their own codes without leaking driver text, and the route-local body cap
refuses oversized streamed bodies while leaving other routes alone.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from tests.support.app import (
    ADMIN_MEMBER,
    TEST_MEMBER,
    FakeSession,
    membership_row,
)
from trendora.api.app import create_app, get_session
from trendora.api.auth import VerifiedClaims, get_verified_claims
from trendora.api.errors import DataUnavailableError
from trendora.planner import (
    PlannerAssigneeInvalidError,
    PlannerPostArchivedError,
    PlannerPostNotFoundError,
    PlannerVersionConflictError,
    PostSummary,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

POST_ID = uuid4()
SECRET = "hunter2-s3cret"
DRIVER_DETAIL = f"commit failed; password={SECRET}"
SUPABASE_URL = "https://example.supabase.co"
BODY_LIMIT = 131_072

VALID_CREATE: dict[str, Any] = {
    "request_id": str(uuid4()),
    "title": "Launch teaser",
    "platform": "Instagram",
    "caption": "Caption text",
    "hook": "Hook line",
    "creative_brief": "Studio brief",
    "asset_links": ["https://example.com/asset"],
    "notes": "Internal note",
    "planned_date": None,
    "assignee_id": None,
}

ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/api/v1/planner/members", None),
    ("GET", "/api/v1/planner/posts", None),
    ("POST", "/api/v1/planner/posts", VALID_CREATE),
    ("GET", f"/api/v1/planner/posts/{POST_ID}", None),
    (
        "PUT",
        f"/api/v1/planner/posts/{POST_ID}",
        {key: value for key, value in VALID_CREATE.items() if key != "request_id"}
        | {"expected_version": 1, "status": "idea"},
    ),
    ("POST", f"/api/v1/planner/posts/{POST_ID}/archive", {"expected_version": 1}),
    ("POST", f"/api/v1/planner/posts/{POST_ID}/restore", {"expected_version": 1}),
]


def _claims(sub: str | None = None) -> VerifiedClaims:
    return VerifiedClaims(sub=sub or str(TEST_MEMBER.user_id), role="authenticated")


def _app(
    *, sub: str | None = None, row: Any = "default"
) -> Any:
    app = create_app()
    app.dependency_overrides[get_verified_claims] = lambda: _claims(sub)
    if row == "default":
        row = membership_row(TEST_MEMBER.user_id)
    app.dependency_overrides[get_session] = lambda: FakeSession(row=row)
    return app


def _client(**kwargs: Any) -> TestClient:
    return TestClient(_app(**kwargs))


def _raw_client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: FakeSession()
    return TestClient(app)


def _raise(error: BaseException) -> None:
    raise error


class TestEveryRouteDeniesUnauthenticatedAccess:
    @pytest.mark.parametrize(("method", "path", "body"), ROUTES)
    def test_missing_authorization_is_401(
        self, method: str, path: str, body: dict[str, Any] | None
    ) -> None:
        client = _raw_client()
        response = client.request(method, path, json=body)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "auth_missing"

    @pytest.mark.parametrize(("method", "path", "body"), ROUTES)
    def test_invalid_token_is_401(
        self, method: str, path: str, body: dict[str, Any] | None
    ) -> None:
        client = _client(sub="not-a-uuid", row=None)
        response = client.request(method, path, json=body)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "auth_invalid_token"

    @pytest.mark.parametrize(("method", "path", "body"), ROUTES)
    def test_nonmember_is_403(
        self, method: str, path: str, body: dict[str, Any] | None
    ) -> None:
        client = _client(row=None)
        response = client.request(method, path, json=body)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "auth_not_member"

    @pytest.mark.parametrize(("method", "path", "body"), ROUTES)
    def test_inactive_member_is_403(
        self, method: str, path: str, body: dict[str, Any] | None
    ) -> None:
        client = _client(
            row=membership_row(TEST_MEMBER.user_id, active=False)
        )
        response = client.request(method, path, json=body)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "auth_inactive"


class TestSharedAccessAndIdentity:
    def test_both_editor_identities_read_the_same_shared_list(
        self, monkeypatch
    ) -> None:
        summary = _summary()
        monkeypatch.setattr(
            "trendora.api.planner.list_posts",
            lambda session, **kwargs: [summary],
        )
        captured: list[dict[str, Any]] = []
        monkeypatch.setattr(
            "trendora.api.planner.list_posts",
            lambda session, **kwargs: captured.append(kwargs) or [summary],
        )

        editor = TestClient(_app())
        admin_editor = TestClient(
            _app(sub=str(ADMIN_MEMBER.user_id), row=membership_row(ADMIN_MEMBER.user_id))
        )
        first = editor.get("/api/v1/planner/posts")
        second = admin_editor.get("/api/v1/planner/posts")

        assert first.status_code == 200 and second.status_code == 200
        assert first.json() == second.json()
        assert first.json()[0]["id"] == str(POST_ID)
        assert captured and set(captured[0]) == {"archived", "limit", "offset"}
        assert captured[0] == {"archived": False, "limit": 50, "offset": 0}

    def test_actor_id_comes_from_the_dependency(self, monkeypatch) -> None:
        seen: dict[str, Any] = {}

        def fake_create(session, *, actor_id, data):
            seen["actor_id"] = actor_id
            return POST_ID, True

        monkeypatch.setattr("trendora.api.planner.create_post", fake_create)
        response = _client().post("/api/v1/planner/posts", json=VALID_CREATE)

        assert response.status_code == 201
        assert response.json() == {"id": str(POST_ID)}
        assert seen["actor_id"] == TEST_MEMBER.user_id

    def test_editor_without_admin_rights_reads_assignment_options(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "trendora.api.planner.list_assignees",
            lambda session: [],
        )
        app = _app()
        assert membership_row(TEST_MEMBER.user_id).is_admin is False
        response = TestClient(app).get("/api/v1/planner/members")
        assert response.status_code == 200
        assert response.json() == []

    def test_replay_returns_200_with_the_same_id(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "trendora.api.planner.create_post",
            lambda session, *, actor_id, data: (POST_ID, False),
        )
        response = _client().post("/api/v1/planner/posts", json=VALID_CREATE)
        assert response.status_code == 200
        assert response.json() == {"id": str(POST_ID)}

    def test_old_post_and_other_creator_are_not_filtered(
        self, monkeypatch
    ) -> None:
        old = datetime.now(timezone.utc) - timedelta(days=400)
        monkeypatch.setattr(
            "trendora.api.planner.list_posts",
            lambda session, **kwargs: [
                _summary(id=POST_ID, updated_at=old),
                _summary(id=uuid4(), updated_at=old),
            ],
        )
        response = _client().get("/api/v1/planner/posts")
        assert response.status_code == 200
        assert len(response.json()) == 2
        assert response.json()[0]["updated_at"].startswith(str(old.year))


def _summary(**overrides: Any) -> PostSummary:
    values: dict[str, Any] = {
        "id": POST_ID,
        "title": "Launch teaser",
        "platform": "Instagram",
        "status": "idea",
        "planned_date": None,
        "assignee_id": None,
        "version": 1,
        "updated_at": datetime.now(timezone.utc),
        "archived_at": None,
    }
    values.update(overrides)
    return PostSummary(**values)


class TestSchemaRejectionKeepsFixedEnvelope:
    def test_unsupported_statuses_are_422(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "trendora.api.planner.update_post",
            lambda *args, **kwargs: pytest.fail("no mutation for an invalid body"),
        )
        base = {key: value for key, value in VALID_CREATE.items() if key != "request_id"}
        for status in ("published", "ready", "approved", "review"):
            response = _client().put(
                f"/api/v1/planner/posts/{POST_ID}",
                json=base | {"expected_version": 1, "status": status},
            )
            assert response.status_code == 422
            assert response.json()["error"] == {
                "code": "invalid_request",
                "message": "request validation failed",
            }

    def test_injected_server_owned_fields_are_422(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "trendora.api.planner.create_post",
            lambda *args, **kwargs: pytest.fail("no mutation for an invalid body"),
        )
        for extra in (
            {"created_by": str(TEST_MEMBER.user_id)},
            {"approval": {"approved": True}},
            {"origin": {"report_id": str(uuid4())}},
            {"version": 7},
            {"content_revision": 7},
        ):
            response = _client().post(
                "/api/v1/planner/posts", json=VALID_CREATE | extra
            )
            assert response.status_code == 422, extra
            assert response.json()["error"]["code"] == "invalid_request"

    def test_full_snapshot_with_a_missing_key_is_422(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "trendora.api.planner.update_post",
            lambda *args, **kwargs: pytest.fail("no mutation for an invalid body"),
        )
        body = {
            key: value
            for key, value in VALID_CREATE.items()
            if key not in ("request_id", "notes")
        } | {"expected_version": 1, "status": "idea"}
        response = _client().put(f"/api/v1/planner/posts/{POST_ID}", json=body)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"

    def test_invalid_uuid_path_parameter_is_422(self) -> None:
        response = _client().get("/api/v1/planner/posts/not-a-uuid")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"


class TestConflictAndFailureMapping:
    def test_stale_save_is_409(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "trendora.api.planner.update_post",
            _raiser(PlannerVersionConflictError("post version does not match")),
        )
        body = {key: value for key, value in VALID_CREATE.items() if key != "request_id"}
        response = _client().put(
            f"/api/v1/planner/posts/{POST_ID}",
            json=body | {"expected_version": 1, "status": "idea"},
        )
        assert response.status_code == 409
        assert response.json()["error"] == {
            "code": "planner_version_conflict",
            "message": "post version does not match",
        }

    def test_edit_of_archived_post_is_409(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "trendora.api.planner.update_post",
            _raiser(PlannerPostArchivedError("planner post is archived")),
        )
        body = {key: value for key, value in VALID_CREATE.items() if key != "request_id"}
        response = _client().put(
            f"/api/v1/planner/posts/{POST_ID}",
            json=body | {"expected_version": 1, "status": "idea"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "planner_post_archived"

    def test_missing_post_is_404(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "trendora.api.planner.get_post",
            _raiser(PlannerPostNotFoundError("planner post not found")),
        )
        response = _client().get(f"/api/v1/planner/posts/{POST_ID}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "planner_post_not_found"

    def test_invalid_assignee_is_422(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "trendora.api.planner.update_post",
            _raiser(
                PlannerAssigneeInvalidError("assignee must be an active member")
            ),
        )
        body = {key: value for key, value in VALID_CREATE.items() if key != "request_id"}
        response = _client().put(
            f"/api/v1/planner/posts/{POST_ID}",
            json=body
            | {
                "expected_version": 1,
                "status": "idea",
                "assignee_id": str(uuid4()),
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "planner_assignee_invalid"

    def test_failed_commit_is_503_without_driver_detail(self, monkeypatch) -> None:
        def fail(*args, **kwargs):
            error = DataUnavailableError("planner data is unavailable")
            error.__cause__ = OperationalError(
                "commit planner_posts", {}, Exception(DRIVER_DETAIL)
            )
            raise error

        monkeypatch.setattr("trendora.api.planner.update_post", fail)
        body = {key: value for key, value in VALID_CREATE.items() if key != "request_id"}
        response = _client().put(
            f"/api/v1/planner/posts/{POST_ID}",
            json=body | {"expected_version": 1, "status": "idea"},
        )
        assert response.status_code == 503
        assert response.json()["error"] == {
            "code": "data_unavailable",
            "message": "planner data is unavailable",
        }
        assert SECRET not in response.text

    def test_archive_rules_are_preserved(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "trendora.api.planner.set_archived",
            _raiser(PlannerVersionConflictError("post version does not match")),
        )
        response = _client().post(
            f"/api/v1/planner/posts/{POST_ID}/archive", json={"expected_version": 4}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "planner_version_conflict"

    def test_restore_rules_are_preserved(self, monkeypatch) -> None:
        def fake(session, **kwargs):
            assert kwargs["archived"] is False
            return _read(archived_at=None, version=2)

        monkeypatch.setattr("trendora.api.planner.set_archived", fake)
        response = _client().post(
            f"/api/v1/planner/posts/{POST_ID}/restore", json={"expected_version": 1}
        )
        assert response.status_code == 200
        assert response.json()["archived_at"] is None
        assert response.json()["version"] == 2

    def test_full_snapshot_edit_returns_committed_read(self, monkeypatch) -> None:
        captured: dict[str, Any] = {}

        def fake(session, *, actor_id, post_id, data):
            captured.update(
                actor_id=actor_id,
                post_id=post_id,
                title=data.title,
                status=data.status,
            )
            return _read(title=data.title, version=2)

        monkeypatch.setattr("trendora.api.planner.update_post", fake)
        body = {key: value for key, value in VALID_CREATE.items() if key != "request_id"}
        response = _client().put(
            f"/api/v1/planner/posts/{POST_ID}",
            json=body | {"expected_version": 1, "status": "working", "title": "New"},
        )
        assert response.status_code == 200
        assert captured["actor_id"] == TEST_MEMBER.user_id
        assert captured["post_id"] == POST_ID
        assert captured["title"] == "New"
        assert captured["status"] == "working"
        assert response.json()["version"] == 2


def _read(**overrides: Any):
    from trendora.planner import PostRead

    values: dict[str, Any] = {
        "id": POST_ID,
        "title": "Launch teaser",
        "platform": "Instagram",
        "caption": "Caption text",
        "hook": "Hook line",
        "creative_brief": "Studio brief",
        "asset_links": ["https://example.com/asset"],
        "notes": "Internal note",
        "planned_date": None,
        "assignee_id": None,
        "status": "idea",
        "version": 1,
        "content_revision": 1,
        "created_by": TEST_MEMBER.user_id,
        "updated_by": TEST_MEMBER.user_id,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "archived_at": None,
    }
    values.update(overrides)
    return PostRead(**values)


def _raiser(error: BaseException):
    def raise_error(*args, **kwargs):
        raise error

    return raise_error


class TestNoProviderSeamsAreTouched:
    def test_planner_requests_never_build_ai_or_research_services(
        self, monkeypatch
    ) -> None:
        def boom(*args, **kwargs):
            raise AssertionError("planner routes must not touch provider services")

        for target in (
            "trendora.api.app.build_research_application_service",
            "trendora.api.app.build_ai_provider_config",
            "trendora.research.application.build_research_application_service",
            "trendora.research.ai_provider.build_ai_provider_config",
        ):
            monkeypatch.setattr(target, boom)

        monkeypatch.setattr(
            "trendora.api.planner.list_posts",
            lambda session, **kwargs: [_summary()],
        )
        monkeypatch.setattr(
            "trendora.api.planner.create_post",
            lambda session, *, actor_id, data: (POST_ID, True),
        )

        client = _client()
        assert client.get("/api/v1/planner/posts").status_code == 200
        assert (
            client.post("/api/v1/planner/posts", json=VALID_CREATE).status_code == 201
        )


class TestRouteLocalBodyLimit:
    @pytest.fixture
    def mutation_calls(self, monkeypatch) -> list[str]:
        calls: list[str] = []

        def fake_create(session, *, actor_id, data):
            calls.append("create")
            return POST_ID, True

        monkeypatch.setattr("trendora.api.planner.create_post", fake_create)
        return calls

    def test_only_planner_routes_use_the_limiting_route_class(self) -> None:
        from fastapi.routing import APIRoute

        from trendora.api.planner import PlannerBodyLimitRoute

        planner_routes: list[APIRoute] = []
        other_routes: list[APIRoute] = []
        for entry in _app().routes:
            if isinstance(entry, APIRoute):
                nested = [entry]
            elif hasattr(entry, "original_router"):
                nested = [
                    route
                    for route in entry.original_router.routes
                    if isinstance(route, APIRoute)
                ]
            else:
                continue
            for route in nested:
                if route.path.startswith("/api/v1/planner"):
                    planner_routes.append(route)
                else:
                    other_routes.append(route)

        assert len(planner_routes) == 9, [r.path for r in planner_routes]
        assert all(
            isinstance(route, PlannerBodyLimitRoute) for route in planner_routes
        )
        assert other_routes, "existing non-planner routes must still exist"
        assert all(
            not isinstance(route, PlannerBodyLimitRoute) for route in other_routes
        )

    @pytest.mark.parametrize(
        ("label", "headers"),
        [
            ("missing", {}),
            ("understated", {"content-length": "10"}),
        ],
    )
    def test_missing_or_understated_content_length_still_reads_the_body(
        self, label, headers, mutation_calls
    ) -> None:
        body = _valid_body_bytes()
        status, payload = _asgi_json(
            _app(),
            "POST",
            "/api/v1/planner/posts",
            [body],
            headers=headers,
        )
        assert status == 201, payload
        assert mutation_calls == ["create"]

    def test_multiple_chunks_within_the_cap_reach_normal_validation(
        self, mutation_calls
    ) -> None:
        oversized_title = (
            b'{"title":"' + b"x" * 130_000 + b'",' + _tail_bytes() + b"}"
        )
        assert len(oversized_title) < BODY_LIMIT
        chunks = [
            oversized_title[:4096],
            oversized_title[4096:9000],
            oversized_title[9000:],
        ]
        status, payload = _asgi_json(
            _app(), "POST", "/api/v1/planner/posts", chunks, headers={}
        )
        assert status == 422, payload
        assert payload["error"]["code"] == "invalid_request"
        assert mutation_calls == []

    def test_body_over_the_cap_is_413_with_zero_mutations(
        self, mutation_calls
    ) -> None:
        oversized = b'{"title":"' + b"x" * (BODY_LIMIT + 100) + b'",' + _tail_bytes() + b"}"
        assert len(oversized) > BODY_LIMIT
        chunks = [oversized[:60_000], oversized[60_000:120_000], oversized[120_000:]]
        status, payload = _asgi_json(
            _app(), "POST", "/api/v1/planner/posts", chunks, headers={}
        )
        assert status == 413, payload
        assert payload["error"] == {
            "code": "planner_request_too_large",
            "message": "planner request body is too large",
        }
        assert mutation_calls == []

    def test_over_cap_body_on_put_is_413_with_zero_mutations(
        self, mutation_calls, monkeypatch
    ) -> None:
        updates: list[str] = []
        monkeypatch.setattr(
            "trendora.api.planner.update_post",
            lambda *args, **kwargs: updates.append("update") or _read(),
        )
        oversized = b'{"title":"' + b"x" * (BODY_LIMIT + 100) + b'",' + _tail_bytes() + b"}"
        status, payload = _asgi_json(
            _app(),
            "PUT",
            f"/api/v1/planner/posts/{POST_ID}",
            [oversized],
            headers={"content-length": str(len(oversized))},
        )
        assert status == 413, payload
        assert payload["error"]["code"] == "planner_request_too_large"
        assert updates == []


def _valid_body_bytes() -> bytes:
    import json

    return json.dumps(VALID_CREATE).encode()


def _tail_bytes() -> bytes:
    import json

    tail = {
        key: value for key, value in VALID_CREATE.items() if key != "title"
    }
    encoded = json.dumps(tail).encode().lstrip(b"{")
    return b"" if encoded == b"}" else encoded


def _asgi_json(app, method: str, path: str, chunks: list[bytes], headers: dict):
    async def run() -> tuple[int, Any]:
        import json

        request_headers = [
            (b"host", b"testserver"),
            (b"authorization", b"Bearer token"),
            (b"content-type", b"application/json"),
        ]
        for name, value in headers.items():
            request_headers.append((name.encode(), value.encode()))
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": request_headers,
            "client": ("127.0.0.1", 54321),
            "server": ("testserver", 80),
            "app": app,
            "router": app.router,
        }
        sent: list[dict[str, Any]] = []
        state = {"index": 0}

        async def receive() -> dict[str, Any]:
            index = state["index"]
            state["index"] += 1
            if index < len(chunks):
                return {
                    "type": "http.request",
                    "body": chunks[index],
                    "more_body": index < len(chunks) - 1,
                }
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        await app(scope, receive, send)
        start = next(m for m in sent if m["type"] == "http.response.start")
        body = b"".join(
            m.get("body", b"") for m in sent if m["type"] == "http.response.body"
        )
        return int(start["status"]), json.loads(body) if body else None

    return asyncio.run(run())


class TestRouterImportsFresh:
    def test_planner_modules_import_in_a_fresh_interpreter(self) -> None:
        """Import order must not matter.

        ``trendora.planner`` imports ``trendora.api.errors``, which runs the
        ``trendora.api`` package init, which imports this app module: a
        top-level ``from trendora.api.planner import planner_router`` there
        would close the cycle. The router may only be imported from inside
        ``create_app()``, and this probe imports the service first to prove it.
        """
        env = {
            key: value
            for key, value in os.environ.items()
            if key
            not in {
                "TRENDORA_TEST_DATABASE_URL",
                "TRENDORA_TEST_DISPOSABLE_PG_URL",
                "TRENDORA_LIVE_SMOKE",
            }
        }
        proc = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                "import trendora.planner\n"
                "from trendora.api import create_app\n"
                "import trendora.api.app\n"
                "import trendora.api.planner\n"
                "import trendora.api.admin\n",
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
