"""Deny-by-default guard policy inside the integration suite.

These tests run with no ``TRENDORA_TEST_DATABASE_URL``: they prove that an
ordinary integration test cannot reach a database, an outbound HTTP request,
or a resolver. Fake originals replace the real implementations through
``GUARDS.originals``, so even a broken guard cannot cause external I/O; a
failure shows up as a missed record or a reached fake, not network traffic.
"""

from __future__ import annotations

import socket

import httpx
import pytest
from sqlalchemy import create_engine

from tests.io_guards import GUARDS, GuardTriggered

APP_URL = "postgresql+psycopg://app@app-host:5432/appdb"
HOSTNAME = "guard-policy-probe.invalid"


def test_application_engine_stays_blocked_in_the_integration_suite(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setitem(
        GUARDS.originals, "dialect.connect", lambda *a, **k: calls.append(a)
    )
    engine = create_engine(APP_URL)
    try:
        with GUARDS.expect_io():
            with pytest.raises(GuardTriggered):
                engine.dialect.connect()
    finally:
        engine.dispose()
    assert calls == [], "the application engine must not reach the connect implementation"
    assert any(a.startswith("database:") for a in GUARDS.expected)


def test_ordinary_integration_dns_is_blocked_before_the_resolver(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setitem(
        GUARDS.originals, "getaddrinfo", lambda *a, **k: calls.append(a)
    )
    with GUARDS.expect_io():
        with pytest.raises(GuardTriggered):
            socket.getaddrinfo(HOSTNAME, 443)
    assert calls == [], "the resolver must not be reached"
    assert any(a.startswith("network:") for a in GUARDS.expected)


def test_ordinary_integration_http_is_blocked(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setitem(
        GUARDS.originals, "getaddrinfo", lambda *a, **k: calls.append(a)
    )
    with GUARDS.expect_io():
        with pytest.raises(Exception):
            httpx.get(f"http://{HOSTNAME}/", timeout=1)
    assert calls == [], "the resolver must not be reached"
    assert any(a.startswith("network:") for a in GUARDS.expected)


def test_ordinary_integration_socket_connect_is_blocked(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setitem(
        GUARDS.originals, "socket.connect", lambda sock, addr: calls.append(addr)
    )
    with GUARDS.expect_io():
        with pytest.raises(GuardTriggered):
            socket.create_connection(("127.0.0.1", 9), timeout=1)
    assert calls == [], "the socket original must not be reached"
    assert any(a.startswith("network:") for a in GUARDS.expected)
