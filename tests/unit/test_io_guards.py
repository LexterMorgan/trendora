"""Guard self-tests: unexpected I/O is blocked, recorded, and fails tests.

These are the only tests allowed to record guarded attempts; each attempt
runs inside ``GUARDS.expect_io()`` so the autouse fixture treats it as
explicitly asserted.
"""

from __future__ import annotations

import asyncio
import socket

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from tests.io_guards import GUARDS, GuardTriggered

BLOCKED_DB_URL = "postgresql+psycopg://guard:guard@127.0.0.1:9/guarddb"
BLOCKED_HTTP_URL = "http://127.0.0.1:9/blocked"


def _run_and_catch(action) -> BaseException:
    """Run a guarded action; fail unless something was raised and recorded."""
    try:
        action()
    except BaseException as exc:  # noqa: BLE001 - guard may be wrapped by a library
        assert GUARDS.attempts, "guard must record before raising"
        return exc
    raise AssertionError("guard did not block the attempt")


def _mentions_guard(exc: BaseException) -> bool:
    if isinstance(exc, GuardTriggered):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(_mentions_guard(sub) for sub in exc.exceptions)
    return exc.__cause__ is not None and _mentions_guard(exc.__cause__)


class TestDatabaseGuard:
    def test_real_engine_connect_is_blocked_and_recorded(self) -> None:
        engine = create_engine(BLOCKED_DB_URL)
        with GUARDS.expect_io():
            exc = _run_and_catch(engine.connect)
            assert _mentions_guard(exc), f"expected GuardTriggered, got {exc!r}"
            assert any(a.startswith("database:") for a in GUARDS.attempts)
        assert any(a.startswith("database:") for a in GUARDS.expected)
        assert GUARDS.failures() == []

    def test_database_attempt_without_permission_is_blocked(self) -> None:
        with GUARDS.expect_io():
            with pytest.raises(GuardTriggered):
                GUARDS.note("database", "unpermitted self-test")
        assert any(a.startswith("database:") for a in GUARDS.expected)
        assert GUARDS.failures() == []


class TestNetworkGuard:
    def test_sync_outbound_http_is_blocked_and_recorded(self) -> None:
        with GUARDS.expect_io():
            exc = _run_and_catch(lambda: httpx.get(BLOCKED_HTTP_URL, timeout=1))
            assert _mentions_guard(exc), f"expected GuardTriggered, got {exc!r}"
            assert any(a.startswith("network:") for a in GUARDS.attempts)
        assert any(a.startswith("network:") for a in GUARDS.expected)

    def test_async_outbound_http_is_blocked_and_recorded(self) -> None:
        async def attempt() -> None:
            async with httpx.AsyncClient() as client:
                await client.get(BLOCKED_HTTP_URL, timeout=1)

        with GUARDS.expect_io():
            _run_and_catch(lambda: asyncio.run(attempt()))
            assert any(a.startswith("network:") for a in GUARDS.attempts)
        assert any(a.startswith("network:") for a in GUARDS.expected)

    def test_caught_guard_exception_still_reaches_the_failure_check(self) -> None:
        with GUARDS.expect_io():
            try:
                httpx.get(BLOCKED_HTTP_URL, timeout=1)
            except Exception:  # application-style swallow
                pass
            # The teardown check reads failures(); a caught exception hides nothing.
            assert any(a.startswith("network:") for a in GUARDS.failures())


class TestDnsGuard:
    def test_hostname_resolution_is_blocked_before_the_resolver(self, monkeypatch) -> None:
        calls: list = []
        monkeypatch.setitem(
            GUARDS.originals, "getaddrinfo", lambda *a, **k: calls.append(a)
        )
        with GUARDS.expect_io():
            with pytest.raises(GuardTriggered):
                socket.getaddrinfo("resolver-probe.invalid", 80)
            assert any(a.startswith("network:") for a in GUARDS.attempts)
        assert calls == [], "resolver original must never be reached"
        assert any("resolve" in a for a in GUARDS.expected)

    def test_gethostbyname_is_blocked_before_the_resolver(self, monkeypatch) -> None:
        calls: list = []
        monkeypatch.setitem(
            GUARDS.originals, "gethostbyname", lambda *a, **k: calls.append(a)
        )
        with GUARDS.expect_io():
            with pytest.raises(GuardTriggered):
                socket.gethostbyname("resolver-probe.invalid")
        assert calls == [], "resolver original must never be reached"
        assert any("gethostbyname" in a for a in GUARDS.expected)

    def test_numeric_loopback_resolution_passes_through(self, monkeypatch) -> None:
        calls: list = []
        monkeypatch.setitem(
            GUARDS.originals,
            "getaddrinfo",
            lambda *a, **k: calls.append(a) or [],
        )
        assert socket.getaddrinfo("127.0.0.1", 0) == []
        assert socket.getaddrinfo("::1", 0) == []
        assert socket.getaddrinfo(None, 0) == []
        assert len(calls) == 3
        assert GUARDS.failures() == []


class TestScopedPermission:
    def test_network_permission_reaches_socket_original_without_syscall(
        self, monkeypatch
    ) -> None:
        calls: list = []
        monkeypatch.setitem(
            GUARDS.originals, "socket.connect", lambda sock, addr: calls.append(addr)
        )
        sock = socket.socket()
        try:
            with GUARDS.permit_network():
                sock.connect(("127.0.0.1", 9))
        finally:
            sock.close()
        assert calls == [("127.0.0.1", 9)]
        assert GUARDS.failures() == []

    def test_network_permission_never_covers_database_seams(self, monkeypatch) -> None:
        calls: list = []
        monkeypatch.setitem(
            GUARDS.originals,
            "dialect.connect",
            lambda *a, **k: calls.append(a),
        )
        engine = create_engine(BLOCKED_DB_URL)
        try:
            with GUARDS.permit_network():
                with GUARDS.expect_io():
                    with pytest.raises(GuardTriggered):
                        engine.dialect.connect()
        finally:
            engine.dispose()
        assert calls == [], "live network permission must not enable database access"
        assert any(a.startswith("database:") for a in GUARDS.expected)

    def test_network_permission_restores_after_failure(self) -> None:
        with pytest.raises(RuntimeError, match="fixture setup failed"):
            with GUARDS.permit_network():
                raise RuntimeError("fixture setup failed")
        with GUARDS.expect_io():
            with pytest.raises(GuardTriggered):
                GUARDS.note("network", "after failed permission")
        assert any("after failed permission" in a for a in GUARDS.expected)
        assert GUARDS.failures() == []


class TestHarnessCompatibility:
    def test_mocktransport_and_testclient_still_work(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            assert client.get("http://provider.test/v1/ping").json() == {"ok": True}

        app = FastAPI()

        @app.get("/ping")
        def ping() -> dict:
            return {"pong": True}

        with TestClient(app) as client:
            assert client.get("/ping").json() == {"pong": True}

        assert GUARDS.failures() == []

    def test_expect_io_moves_attempts_out_of_the_failure_check(self) -> None:
        with GUARDS.expect_io():
            try:
                GUARDS.note("database", "explicitly asserted self-test")
            except GuardTriggered:
                pass
            assert GUARDS.failures()
        assert GUARDS.failures() == []
        assert GUARDS.expected == ["database: explicitly asserted self-test"]

    def test_guards_are_installed_before_collection(self) -> None:
        import socket
        from sqlalchemy.engine.default import DefaultDialect

        assert "connect" in vars(socket.socket)
        assert "socket_connect" in socket.socket.connect.__qualname__
        assert "dialect_connect" in DefaultDialect.connect.__qualname__
