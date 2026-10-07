"""Approved destructive engine at the DBAPI boundary.

Every seam is mocked: ``psycopg.connect`` records the call and stops it, so
nothing connects, no migrations run, and no installs happen. These tests
prove:

* inherited ``PGHOSTADDR``/``PGSERVICE`` (or any ``PG*`` override) rejects
  the approved engine before the driver is reached, with names only;
* destructive fixtures execute through ``approved_engine``, not through the
  unapproved ``test_engine`` plus an unused approval request;
* clean approved configuration reaches exactly the validated loopback
  endpoint and nothing else.
"""

from __future__ import annotations

import inspect

import psycopg
import pytest

from tests.integration import conftest as integration_conftest
from tests.integration.test_gate_a_members_admin import memberships
from tests.integration.test_gate_a_report_history import report_session
from tests.io_guards import GUARDS
from tests.pg_harness import Target, UnsafeTargetError

APPROVED = Target(
    host="127.0.0.1",
    port=5432,
    user="tester",
    password="s3cret",
    database="gatea",
    ips=frozenset({"127.0.0.1"}),
)


@pytest.fixture
def dbapi_boundary(monkeypatch) -> list[tuple[tuple, dict]]:
    """Record DBAPI connect attempts; nothing may reach a real connection."""

    calls: list[tuple[tuple, dict]] = []

    def record(*args, **kwargs):
        calls.append((args, kwargs))
        raise RuntimeError("stop at dbapi boundary")

    monkeypatch.setattr(psycopg, "connect", record)
    return calls


class TestRejectedBeforeConnecting:
    def test_inherited_libpq_overrides_fail_closed(
        self, monkeypatch, dbapi_boundary
    ) -> None:
        monkeypatch.setenv("PGHOSTADDR", "203.0.113.9")
        monkeypatch.setenv("PGSERVICE", "reroute")
        with pytest.raises(UnsafeTargetError) as excinfo:
            integration_conftest.build_approved_engine(APPROVED)
        message = str(excinfo.value)
        assert "PGHOSTADDR" in message
        assert "PGSERVICE" in message
        assert "203.0.113.9" not in message
        assert "reroute" not in message
        assert dbapi_boundary == []


class TestDestructiveFixturesExecuteThroughApprovedEngine:
    def test_memberships_takes_only_the_approved_engine(self) -> None:
        assert list(inspect.signature(memberships).parameters) == [
            "approved_engine"
        ]

    def test_report_session_takes_only_the_approved_engine(self) -> None:
        assert list(inspect.signature(report_session).parameters) == [
            "approved_engine"
        ]

    def test_approved_engine_is_gated_on_approval_and_schema(self) -> None:
        params = inspect.signature(
            integration_conftest.approved_engine
        ).parameters
        assert list(params) == ["approved_test_db", "scratch_schema"]


class TestCleanApprovedTargetOnly:
    def test_connect_reaches_only_the_validated_endpoint(
        self, dbapi_boundary
    ) -> None:
        engine = integration_conftest.build_approved_engine(APPROVED, env={})
        try:
            with GUARDS.permit_engine(engine):
                with pytest.raises(RuntimeError, match="stop at dbapi boundary"):
                    engine.connect()
        finally:
            engine.dispose()
        assert len(dbapi_boundary) == 1
        _args, kwargs = dbapi_boundary[0]
        assert kwargs["host"] == APPROVED.host
        assert str(kwargs["port"]) == str(APPROVED.port)
        assert kwargs["dbname"] == APPROVED.database
        assert kwargs["user"] == APPROVED.user
        assert "hostaddr" not in kwargs
