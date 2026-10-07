"""Mocked regressions for the disposable PostgreSQL harness.

No real database, no subprocess, no DNS: every seam is monkeypatched. These
tests prove the safety contract the migration tests rely on:

* missing opt-in skips (or returns ``None``) with zero subprocess calls;
* unapproved targets are rejected before any subprocess executes;
* pre-existing databases and roles stop the run instead of being touched;
* cleanup drops only resources this run created;
* connection credentials never appear in failure messages.
"""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from _pytest.outcomes import Skipped
from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
from sqlalchemy.engine import make_url

from tests import pg_harness
from tests.pg_harness import (
    ALEMBIC_TIMEOUT_SECONDS,
    ENV_DISPOSABLE_PG_URL,
    PSQL_TIMEOUT_SECONDS,
    HarnessError,
    Target,
    UnsafeTargetError,
    alembic_env_if_approved,
    approved_test_target_or_skip,
    cleanup_owned,
    create_owned_database,
    disposable_cluster_or_skip,
    disposable_target_or_none,
    drop_owned_role,
    ensure_owned_role,
    preflight_roles_absent,
    psql,
    run_checked,
    url_secrets,
    validate_target,
)

TEST_URL = "postgresql://tester:s3cret@127.0.0.1:5432/appdb"
REMOTE_URL = "postgresql://tester:s3cret@db.example.com:5432/postgres"
OK_IPS = frozenset({"127.0.0.1"})
APPROVED_URL = "postgresql://tester@127.0.0.1:5432/postgres"
REPRO_URL = (
    "postgresql+psycopg://tester@127.0.0.1:5432/testdb"
    "?host=203.0.113.9&port=6543"
)
INTEGRATION_DIR = Path(__file__).resolve().parents[1] / "integration"


def _connect_args(url: str) -> dict:
    """Actual connection arguments SQLAlchemy would pass to the driver."""
    _args, opts = PGDialect_psycopg().create_connect_args(make_url(url))
    return opts


def _endpoint_from_psql_call(call: dict) -> tuple[str, str]:
    argv = call["argv"]
    return argv[argv.index("-h") + 1], argv[argv.index("-p") + 1]


def _target(**overrides) -> Target:
    base = dict(
        host="127.0.0.1",
        port=5432,
        user="tester",
        password="s3cret",
        database="postgres",
        ips=OK_IPS,
    )
    base.update(overrides)
    return Target(**base)


@pytest.fixture
def forbid_subprocess(monkeypatch) -> None:
    """Any subprocess attempt fails the test: proves zero subprocess work."""

    def explode(*args, **kwargs):
        raise AssertionError(f"subprocess must not run: {args[0]!r}")

    monkeypatch.setattr(pg_harness, "_run_subprocess", explode)


@pytest.fixture
def record_subprocess(monkeypatch):
    """Record subprocess attempts and answer SQL probes via ``sql_output``."""
    calls: list[dict] = []

    def make(sql_output=None):
        def fake(argv, *, timeout, env=None, cwd=None):
            sql = list(argv)[-1] if argv else ""
            calls.append({"argv": list(argv), "timeout": timeout, "env": env, "sql": sql})
            return SimpleNamespace(
                returncode=0,
                stdout=sql_output(sql) if sql_output else "",
                stderr="",
            )

        monkeypatch.setattr(pg_harness, "_run_subprocess", fake)
        return calls

    return make


class TestMissingOptIn:
    def test_target_resolution_returns_none_without_subprocess(
        self, monkeypatch, forbid_subprocess
    ) -> None:
        monkeypatch.delenv(ENV_DISPOSABLE_PG_URL, raising=False)
        assert disposable_target_or_none() is None
        assert alembic_env_if_approved(TEST_URL, {"A": "1"}) is None

    def test_cluster_entry_point_skips_without_subprocess(
        self, monkeypatch, forbid_subprocess
    ) -> None:
        monkeypatch.delenv(ENV_DISPOSABLE_PG_URL, raising=False)
        with pytest.raises(Skipped, match=ENV_DISPOSABLE_PG_URL):
            disposable_cluster_or_skip()

    def test_blank_opt_in_counts_as_missing(
        self, monkeypatch, forbid_subprocess
    ) -> None:
        monkeypatch.setenv(ENV_DISPOSABLE_PG_URL, "   ")
        assert disposable_target_or_none() is None


class TestUnapprovedTargetsRejectedBeforeExecution:
    def test_non_loopback_host_is_rejected(
        self, monkeypatch, forbid_subprocess
    ) -> None:
        monkeypatch.setenv(ENV_DISPOSABLE_PG_URL, REMOTE_URL)
        monkeypatch.setattr(
            pg_harness, "_resolve_ips", lambda host, port: frozenset({"203.0.113.9"})
        )
        with pytest.raises(UnsafeTargetError, match="loopback") as excinfo:
            disposable_target_or_none()
        message = str(excinfo.value)
        assert "s3cret" not in message
        assert "tester" not in message

    def test_mixed_resolution_is_rejected(self, monkeypatch, forbid_subprocess) -> None:
        monkeypatch.setenv(ENV_DISPOSABLE_PG_URL, REMOTE_URL)
        monkeypatch.setattr(
            pg_harness,
            "_resolve_ips",
            lambda host, port: frozenset({"127.0.0.1", "203.0.113.9"}),
        )
        with pytest.raises(UnsafeTargetError, match="loopback"):
            disposable_target_or_none()

    def test_dns_failure_is_rejected(self, monkeypatch, forbid_subprocess) -> None:
        monkeypatch.setenv(ENV_DISPOSABLE_PG_URL, REMOTE_URL)

        def fail(host, port):
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

        monkeypatch.setattr(pg_harness, "_resolve_ips", fail)
        with pytest.raises(UnsafeTargetError, match="cannot resolve"):
            disposable_target_or_none()

    def test_non_postgresql_scheme_is_rejected(
        self, monkeypatch, forbid_subprocess
    ) -> None:
        monkeypatch.setenv(ENV_DISPOSABLE_PG_URL, "mysql://tester:s3cret@127.0.0.1/db")
        with pytest.raises(UnsafeTargetError, match="scheme"):
            disposable_target_or_none()

    def test_endpoint_mismatch_is_rejected_before_alembic(
        self, monkeypatch, forbid_subprocess
    ) -> None:
        monkeypatch.setenv(ENV_DISPOSABLE_PG_URL, "postgresql://tester@127.0.0.1:5433/postgres")
        monkeypatch.setattr(pg_harness, "_resolve_ips", lambda host, port: OK_IPS)
        with pytest.raises(UnsafeTargetError, match="same loopback endpoint"):
            alembic_env_if_approved(TEST_URL, {})

    def test_non_loopback_test_url_is_rejected_with_approved_cluster(
        self, monkeypatch, forbid_subprocess
    ) -> None:
        monkeypatch.setenv(ENV_DISPOSABLE_PG_URL, "postgresql://tester@127.0.0.1:5432/postgres")
        monkeypatch.setattr(
            pg_harness,
            "_resolve_ips",
            lambda host, port: OK_IPS if host == "127.0.0.1" else frozenset({"203.0.113.9"}),
        )
        with pytest.raises(UnsafeTargetError, match="loopback"):
            alembic_env_if_approved(REMOTE_URL, {})

    def test_approved_cluster_yields_env(self, monkeypatch, forbid_subprocess) -> None:
        monkeypatch.setenv(ENV_DISPOSABLE_PG_URL, "postgresql://tester@127.0.0.1:5432/postgres")
        monkeypatch.setattr(pg_harness, "_resolve_ips", lambda host, port: OK_IPS)
        env = alembic_env_if_approved(TEST_URL, {"KEEP": "1"})
        assert env is not None
        assert env["DATABASE_URL"] == (
            "postgresql+psycopg://tester:s3cret@127.0.0.1:5432/appdb"
        )
        assert env["KEEP"] == "1"

    def test_validate_target_parses_url_fields(self, monkeypatch) -> None:
        monkeypatch.setattr(pg_harness, "_resolve_ips", lambda host, port: OK_IPS)
        target = validate_target(TEST_URL)
        assert (target.host, target.port, target.user, target.password) == (
            "127.0.0.1",
            5432,
            "tester",
            "s3cret",
        )
        assert target.database == "appdb"
        assert target.secrets == ("s3cret", "tester")


class TestExistingObjectsStopRun:
    def test_preflight_refuses_existing_role_with_select_only(
        self, record_subprocess
    ) -> None:
        calls = record_subprocess(lambda sql: "1" if "pg_roles" in sql else "0")
        with pytest.raises(UnsafeTargetError, match="pre-existing roles"):
            preflight_roles_absent(_target(), ("anon", "authenticated"))
        assert len(calls) == 1
        assert calls[0]["sql"].lstrip().startswith("SELECT")
        assert "CREATE" not in calls[0]["sql"]
        assert "DROP" not in calls[0]["sql"]

    def test_existing_database_is_not_dropped_or_reused(
        self, record_subprocess
    ) -> None:
        calls = record_subprocess(lambda sql: "1" if "pg_database" in sql else "0")
        with pytest.raises(UnsafeTargetError, match="already exists"):
            create_owned_database(_target(), "trendora_gatea_owned")
        assert all("CREATE DATABASE" not in c["sql"] for c in calls)
        assert all("DROP" not in c["sql"] for c in calls)

    def test_ensure_owned_role_refuses_existing_role(
        self, record_subprocess
    ) -> None:
        calls = record_subprocess(lambda sql: "1" if "pg_roles" in sql else "0")
        owned: list[str] = []
        with pytest.raises(UnsafeTargetError, match="pre-existing roles"):
            ensure_owned_role(_target(), "anon", owned)
        assert owned == []
        assert all("CREATE ROLE" not in c["sql"] for c in calls)

    def test_ensure_owned_role_tracks_only_what_it_created(
        self, record_subprocess
    ) -> None:
        calls = record_subprocess(lambda sql: "0")
        owned: list[str] = []
        ensure_owned_role(_target(), "anon", owned)
        assert owned == ["anon"]
        assert any("CREATE ROLE" in c["sql"] for c in calls)


class TestCleanupOwnedOnly:
    def test_cleanup_drops_exactly_the_owned_resources(
        self, record_subprocess
    ) -> None:
        calls = record_subprocess(lambda sql: "0")
        cleanup_owned(
            _target(),
            databases=["trendora_gatea_deadbeef"],
            roles=["anon"],
        )
        sqls = [c["sql"] for c in calls]
        assert any('DROP DATABASE "trendora_gatea_deadbeef"' in s for s in sqls)
        assert any('DROP ROLE "anon"' in s for s in sqls)
        assert not any("authenticated" in s for s in sqls), (
            "a role this run never created must never appear in cleanup SQL"
        )
        assert not any("FORCE" in s and "DROP DATABASE" not in s for s in sqls)

    def test_drop_owned_role_refuses_untracked_existing_role(
        self, record_subprocess
    ) -> None:
        calls = record_subprocess(lambda sql: "1" if "pg_roles" in sql else "0")
        with pytest.raises(UnsafeTargetError, match="not created by this run"):
            drop_owned_role(_target(), "anon", [])
        assert all("DROP ROLE" not in c["sql"] for c in calls)

    def test_drop_owned_role_is_noop_when_already_absent(
        self, record_subprocess
    ) -> None:
        calls = record_subprocess(lambda sql: "0")
        drop_owned_role(_target(), "anon", [])
        assert all("DROP ROLE" not in c["sql"] for c in calls)

    def test_drop_owned_role_removes_tracked_role(
        self, record_subprocess
    ) -> None:
        calls = record_subprocess(lambda sql: "0")
        owned = ["anon"]
        drop_owned_role(_target(), "anon", owned)
        assert owned == []
        assert any('DROP ROLE "anon"' in c["sql"] for c in calls)


class TestCredentialRedaction:
    def test_failure_message_never_contains_credentials(self, monkeypatch) -> None:
        def fake(argv, *, timeout, env=None, cwd=None):
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr=(
                    'FATAL: password authentication failed for user "tester"\n'
                    "connection string contained s3cret"
                ),
            )

        monkeypatch.setattr(pg_harness, "_run_subprocess", fake)
        with pytest.raises(HarnessError) as excinfo:
            run_checked(["psql"], timeout=5, secrets=("s3cret", "tester"))
        message = str(excinfo.value)
        assert "s3cret" not in message
        assert "tester" not in message
        assert "[redacted]" in message
        assert "authentication failed" in message, "diagnostics stay, only credentials go"

    def test_timeout_message_never_contains_credentials(self, monkeypatch) -> None:
        def fake(argv, *, timeout, env=None, cwd=None):
            raise subprocess.TimeoutExpired(
                cmd=list(argv), timeout=timeout, output="partial s3cret", stderr="end tester"
            )

        monkeypatch.setattr(pg_harness, "_run_subprocess", fake)
        with pytest.raises(HarnessError, match="timed out") as excinfo:
            run_checked(["psql"], timeout=5, secrets=("s3cret", "tester"))
        message = str(excinfo.value)
        assert "s3cret" not in message
        assert "tester" not in message

    def test_psql_passes_password_via_env_not_argv(self, record_subprocess) -> None:
        calls = record_subprocess(lambda sql: "0")
        psql(_target(), "SELECT 1")
        argv = calls[0]["argv"]
        assert "s3cret" not in " ".join(argv)
        assert "s3cret" not in argv
        assert calls[0]["env"]["PGPASSWORD"] == "s3cret"

    def test_psql_enforces_its_timeout(self, record_subprocess) -> None:
        calls = record_subprocess(lambda sql: "0")
        psql(_target(), "SELECT 1")
        assert calls[0]["timeout"] == PSQL_TIMEOUT_SECONDS

    def test_url_secrets_extracts_user_and_password(self) -> None:
        assert url_secrets(TEST_URL) == ("s3cret", "tester")
        assert url_secrets("postgresql://127.0.0.1/db") == ()

    def test_url_secrets_includes_url_encoded_forms(self) -> None:
        secrets = url_secrets("postgresql://te%40ster:p%40ss@127.0.0.1:5432/db")
        assert "te@ster" in secrets
        assert "te%40ster" in secrets
        assert "p@ss" in secrets
        assert "p%40ss" in secrets


class TestEffectiveTargetMismatchBlocked:
    """The validated URL fields must be the fields the driver connects to."""

    def test_query_parameters_override_host_and_port_in_the_dialect(self) -> None:
        # Documents the hazard: SQLAlchemy lets query options win over the
        # URL host/port, so a URL approved by field inspection could still
        # connect somewhere else. The gate refuses such URLs outright.
        opts = _connect_args(REPRO_URL)
        assert opts["host"] == "203.0.113.9"
        assert str(opts["port"]) == "6543"

    def test_repro_url_rejected_before_resolution_or_subprocess(
        self, monkeypatch, forbid_subprocess
    ) -> None:
        monkeypatch.setenv(ENV_DISPOSABLE_PG_URL, APPROVED_URL)
        resolved: list[str] = []
        monkeypatch.setattr(
            pg_harness,
            "_resolve_ips",
            lambda host, port: (resolved.append(host), OK_IPS)[1],
        )
        with pytest.raises(UnsafeTargetError, match="query"):
            alembic_env_if_approved(REPRO_URL, {})
        assert resolved == ["127.0.0.1"], (
            "the cluster validated once; the query-bearing test URL must be "
            "rejected before its own resolution"
        )

    def test_query_on_cluster_url_rejected_without_resolution(
        self, monkeypatch, forbid_subprocess
    ) -> None:
        monkeypatch.setenv(ENV_DISPOSABLE_PG_URL, REPRO_URL)

        def explode(host: str, port: int):
            raise AssertionError("a query-bearing URL must not be resolved")

        monkeypatch.setattr(pg_harness, "_resolve_ips", explode)
        with pytest.raises(UnsafeTargetError, match="query"):
            disposable_target_or_none()

    def test_fragment_rejected_before_resolution(
        self, monkeypatch, forbid_subprocess
    ) -> None:
        monkeypatch.setenv(
            ENV_DISPOSABLE_PG_URL,
            "postgresql://tester@127.0.0.1:5432/postgres#fragment",
        )

        def explode(host: str, port: int):
            raise AssertionError("a fragment-bearing URL must not be resolved")

        monkeypatch.setattr(pg_harness, "_resolve_ips", explode)
        with pytest.raises(UnsafeTargetError, match="fragment"):
            disposable_target_or_none()

    @pytest.mark.parametrize(
        "scheme", ["postgresql+asyncpg", "postgresqlbogus", "mysql"]
    )
    def test_unsupported_scheme_rejected_before_resolution(
        self, scheme: str, monkeypatch, forbid_subprocess
    ) -> None:
        monkeypatch.setenv(
            ENV_DISPOSABLE_PG_URL, f"{scheme}://tester@127.0.0.1:5432/db"
        )

        def explode(host: str, port: int):
            raise AssertionError("an unsupported scheme must not be resolved")

        monkeypatch.setattr(pg_harness, "_resolve_ips", explode)
        with pytest.raises(UnsafeTargetError, match="scheme"):
            disposable_target_or_none()

    def test_alembic_env_is_canonical_and_libpq_free(
        self, monkeypatch, forbid_subprocess
    ) -> None:
        monkeypatch.setenv(ENV_DISPOSABLE_PG_URL, APPROVED_URL)
        monkeypatch.setattr(pg_harness, "_resolve_ips", lambda host, port: OK_IPS)
        env = alembic_env_if_approved(
            TEST_URL,
            {
                "PGHOSTADDR": "203.0.113.9",
                "PGSERVICE": "evil-service",
                "PGHOST": "elsewhere",
                "PGPASSWORD": "env-spoof",
                "PATH": "/usr/bin",
            },
        )
        assert env is not None
        canonical = env["DATABASE_URL"]
        parsed = make_url(canonical)
        assert parsed.query == {}
        assert "#" not in canonical
        assert parsed.drivername == "postgresql+psycopg"
        opts = _connect_args(canonical)
        assert opts["host"] == "127.0.0.1"
        assert str(opts["port"]) == "5432"
        assert "hostaddr" not in opts
        for key in ("PGHOSTADDR", "PGSERVICE", "PGHOST", "PGPASSWORD"):
            assert key not in env
        assert env["PATH"] == "/usr/bin"

    def test_psql_argv_and_env_match_the_validated_endpoint(
        self, monkeypatch, record_subprocess
    ) -> None:
        monkeypatch.setenv("PGHOSTADDR", "203.0.113.9")
        monkeypatch.setenv("PGSERVICE", "evil-service")
        monkeypatch.setenv("PGPASSWORD", "env-spoof")
        calls = record_subprocess(lambda sql: "0")
        psql(_target(), "SELECT 1")
        assert _endpoint_from_psql_call(calls[0]) == ("127.0.0.1", "5432")
        env = calls[0]["env"]
        assert "PGHOSTADDR" not in env
        assert "PGSERVICE" not in env
        assert env["PGPASSWORD"] == "s3cret"

    def test_psql_and_alembic_use_the_same_endpoint(
        self, monkeypatch, record_subprocess
    ) -> None:
        monkeypatch.setenv(ENV_DISPOSABLE_PG_URL, APPROVED_URL)
        monkeypatch.setattr(pg_harness, "_resolve_ips", lambda host, port: OK_IPS)
        env = alembic_env_if_approved(
            TEST_URL, {"PGHOSTADDR": "203.0.113.9", "KEEP": "1"}
        )
        assert env is not None
        calls = record_subprocess(lambda sql: "0")
        psql(validate_target(TEST_URL), "SELECT 1")
        opts = _connect_args(env["DATABASE_URL"])
        assert (str(opts["host"]), str(opts["port"])) == _endpoint_from_psql_call(
            calls[0]
        )


class TestDestructiveApproval:
    def test_missing_approval_skips_without_subprocess(
        self, monkeypatch, forbid_subprocess
    ) -> None:
        monkeypatch.delenv(ENV_DISPOSABLE_PG_URL, raising=False)
        with pytest.raises(Skipped, match="disposable-target approval"):
            approved_test_target_or_skip(TEST_URL)

    def test_approval_returns_the_validated_test_target(
        self, monkeypatch, forbid_subprocess
    ) -> None:
        monkeypatch.setenv(ENV_DISPOSABLE_PG_URL, APPROVED_URL)
        monkeypatch.setattr(pg_harness, "_resolve_ips", lambda host, port: OK_IPS)
        target = approved_test_target_or_skip(TEST_URL)
        assert (target.host, target.port) == ("127.0.0.1", 5432)

    def test_query_bearing_test_url_fails_without_subprocess(
        self, monkeypatch, forbid_subprocess
    ) -> None:
        monkeypatch.setenv(ENV_DISPOSABLE_PG_URL, APPROVED_URL)
        monkeypatch.setattr(pg_harness, "_resolve_ips", lambda host, port: OK_IPS)
        with pytest.raises(UnsafeTargetError, match="query"):
            approved_test_target_or_skip(REPRO_URL)


class TestDestructiveFixturesRequestApproval:
    def test_shared_data_fixtures_run_on_the_approved_engine(self) -> None:
        flagged: list[str] = []
        for path in sorted(INTEGRATION_DIR.glob("test_*.py")):
            source = path.read_text(encoding="utf-8")
            mutates_shared = "TRUNCATE" in source or ".delete()" in source
            if not mutates_shared:
                continue
            flagged.append(path.name)
            assert "approved_engine" in source, (
                f"{path.name} mutates shared fixture data without executing "
                "through the approved engine"
            )
            assert "test_engine" not in source, (
                f"{path.name} mutates shared fixture data through the "
                "unapproved test_engine, which inherits libpq overrides"
            )
        assert "test_gate_a_members_admin.py" in flagged
        assert "test_gate_a_report_history.py" in flagged


def test_role_state_alembic_strips_libpq_overrides(
    monkeypatch, forbid_subprocess
) -> None:
    """The Gate A migration helper must not inherit ``PG*`` routing settings.

    Its canonical ``DATABASE_URL`` does not neutralize ``PGHOSTADDR`` or
    ``PGSERVICE``: libpq still honors those, so psql and alembic could reach
    different endpoints. In-memory ``Target``/``OwnedCluster`` only, no DNS,
    subprocess, or database call.
    """
    from tests.integration import test_gate_a_migration as migration

    target = Target(
        host="127.0.0.1",
        port=5432,
        user="tester",
        password="s3cret",
        database="postgres",
        ips=OK_IPS,
    )
    owned = migration.OwnedCluster(target=target, database="trendora_gatea_unit")
    monkeypatch.setenv("PGHOSTADDR", "203.0.113.9")
    monkeypatch.setenv("PGSERVICE", "evil-service")
    monkeypatch.setenv("PGPASSWORD", "env-spoof")
    monkeypatch.setenv("KEEP_ME", "kept")

    captured: dict[str, object] = {}

    def fake_run_checked(argv, **kwargs):
        captured["argv"] = list(argv)
        captured.update(kwargs)
        return ""

    monkeypatch.setattr(migration, "run_checked", fake_run_checked)

    migration._alembic(owned, "upgrade", "head")

    env = captured["env"]
    assert isinstance(env, dict)
    assert [key for key in env if key.startswith("PG")] == []
    assert env["DATABASE_URL"] == target.url_for(owned.database)
    assert env["KEEP_ME"] == "kept"
    assert captured["cwd"] == migration.ROOT
    assert captured["timeout"] == ALEMBIC_TIMEOUT_SECONDS
    assert captured["secrets"] == target.secrets
    assert captured["argv"][1:] == ["-m", "alembic", "upgrade", "head"]
