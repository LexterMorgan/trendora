"""Regression: integration database wiring uses only TRENDORA_TEST_DATABASE_URL.

No test here opens a connection: engine creation is faked and URL resolution
runs against a controlled environment. They fail against the old wiring, which
fell back to the application DATABASE_URL / settings engine.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest
from _pytest.outcomes import Skipped

import trendora.db.session as application_session
from tests.integration import conftest as integration_conftest
from tests.io_guards import GUARDS, GuardTriggered

APP_URL = "postgresql+psycopg://app-user@app-host:5432/appdb"
TEST_URL = "postgresql+psycopg://test-user@test-host:5432/testdb"

DB_MODULES = (
    "test_analytics",
    "test_forecasting",
)


class TestTestUrlResolution:
    def test_missing_test_url_never_falls_back(self, monkeypatch) -> None:
        monkeypatch.delenv("TRENDORA_TEST_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", APP_URL)
        assert integration_conftest.resolve_test_database_url() is None

    def test_blank_test_url_never_falls_back(self, monkeypatch) -> None:
        monkeypatch.setenv("TRENDORA_TEST_DATABASE_URL", "   ")
        monkeypatch.setenv("DATABASE_URL", APP_URL)
        assert integration_conftest.resolve_test_database_url() is None

    def test_test_url_wins_over_application_url(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", APP_URL)
        monkeypatch.setenv("TRENDORA_TEST_DATABASE_URL", TEST_URL)
        assert integration_conftest.resolve_test_database_url() == TEST_URL

    def test_resolver_never_reads_application_settings(self, monkeypatch) -> None:
        import trendora.config as config

        def boom() -> object:
            raise AssertionError("application settings must not be read")

        monkeypatch.setattr(config, "get_settings", boom)
        monkeypatch.delenv("TRENDORA_TEST_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", APP_URL)
        assert not hasattr(integration_conftest, "get_settings")
        assert integration_conftest.resolve_test_database_url() is None

    def test_missing_test_url_skips_database_integration_tests(self, monkeypatch) -> None:
        monkeypatch.delenv("TRENDORA_TEST_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", APP_URL)
        with pytest.raises(Skipped) as excinfo:
            integration_conftest.require_test_database_url()
        assert "TRENDORA_TEST_DATABASE_URL" in str(excinfo.value)


class TestDedicatedTestEngine:
    def test_engine_is_built_from_the_test_url_and_disposed(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", APP_URL)
        monkeypatch.setenv("TRENDORA_TEST_DATABASE_URL", TEST_URL)
        created: list[tuple[str, dict]] = []
        disposed: list[bool] = []

        class FakeEngine:
            def dispose(self) -> None:
                disposed.append(True)

        def fake_create_engine(url: str, **kwargs) -> FakeEngine:
            created.append((url, kwargs))
            return FakeEngine()

        monkeypatch.setattr(integration_conftest, "create_engine", fake_create_engine)
        existing_application_engine = object()
        monkeypatch.setattr(application_session, "_engine", existing_application_engine)
        url = integration_conftest.resolve_test_database_url()
        with integration_conftest.test_engine_scope(url) as engine:
            assert isinstance(engine, FakeEngine)
        assert created, "engine must be created through the dedicated builder"
        assert created[0][0] == TEST_URL
        assert created[0][0] != APP_URL
        assert disposed == [True]
        assert application_session._engine is existing_application_engine

    def test_conftest_never_touches_the_application_engine(self) -> None:
        assert not hasattr(integration_conftest, "get_engine")
        assert not hasattr(integration_conftest, "reset_engine")

    def test_shared_db_session_fixture_consumes_the_test_engine(self) -> None:
        params = inspect.signature(integration_conftest.db_session).parameters
        assert list(params) == ["test_engine"]

    def test_dedicated_engine_reaches_the_original_connect_implementation(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("TRENDORA_TEST_DATABASE_URL", TEST_URL)
        calls: list = []
        monkeypatch.setitem(
            GUARDS.originals,
            "dialect.connect",
            lambda *a, **k: calls.append(a) or "mock-connection",
        )
        url = integration_conftest.resolve_test_database_url()
        with integration_conftest.test_engine_scope(url) as engine:
            assert engine.dialect.connect() == "mock-connection"
            assert GUARDS.failures() == []
        assert calls, "the dedicated engine must reach the connect implementation"

    def test_engine_permission_is_revoked_when_scope_fails(self, monkeypatch) -> None:
        monkeypatch.setenv("TRENDORA_TEST_DATABASE_URL", TEST_URL)
        disposed: list[bool] = []
        dialect = object()

        class FakeEngine:
            def dispose(self) -> None:
                disposed.append(True)

        fake = FakeEngine()
        fake.dialect = dialect
        monkeypatch.setattr(
            integration_conftest, "create_engine", lambda url, **kwargs: fake
        )
        with pytest.raises(RuntimeError, match="fixture setup failed"):
            with integration_conftest.test_engine_scope(TEST_URL):
                GUARDS.note("database", "inside permitted scope", dialect=dialect)
                raise RuntimeError("fixture setup failed")
        assert GUARDS.failures() == []
        assert disposed == [True], "a failing scope must still dispose the engine"
        with GUARDS.expect_io():
            with pytest.raises(GuardTriggered):
                GUARDS.note("database", "after failed scope", dialect=dialect)
        assert any("after failed scope" in a for a in GUARDS.expected)


class TestIntegrationFixtureWiring:
    @pytest.mark.parametrize("revision, accepted", [
        ("0008_report_source_expiry", True),
        ("0007_origin_collected_at_nullable", False),
    ])
    def test_revision_check_requires_the_report_expiry_migration(self, revision, accepted):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from tests.integration.test_database import test_alembic_revision

        connection = SimpleNamespace(execute=lambda statement: SimpleNamespace(
            scalar_one=lambda: revision,
        ))
        engine = SimpleNamespace(connect=lambda: nullcontext(connection))
        if accepted:
            test_alembic_revision(engine)
        else:
            with pytest.raises(AssertionError):
                test_alembic_revision(engine)

    def test_no_integration_module_uses_the_application_engine(self) -> None:
        root = Path(integration_conftest.__file__).parent
        for path in sorted(root.glob("test_*.py")):
            source = path.read_text(encoding="utf-8")
            assert "get_engine" not in source, path.name
            assert "reset_engine" not in source, path.name

    def test_local_db_session_fixtures_take_the_test_engine(self) -> None:
        for name in DB_MODULES:
            module = importlib.import_module(f"tests.integration.{name}")
            params = inspect.signature(module.db_session).parameters
            assert "test_engine" in params, name
            assert "database_url" not in params, name

    def test_report_smoke_test_mocks_report_persistence(self) -> None:
        root = Path(integration_conftest.__file__).parent
        source = (root / "test_research_youtube_report_live.py").read_text(encoding="utf-8")
        assert "_persist_research_report" in source
