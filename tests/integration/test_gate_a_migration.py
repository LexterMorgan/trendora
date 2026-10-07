"""Gate A: migration 0003: role states, RLS, and downgrade safety.

Roles are cluster-wide, so these tests run only against an owner-approved
disposable PostgreSQL cluster (``TRENDORA_TEST_DISPOSABLE_PG_URL``). Without
that opt-in they skip and run zero subprocess operations. The target is
validated in-process (PostgreSQL scheme, loopback resolution) before any
psql/alembic call. Each run creates one uniquely named database and only the
``anon`` / ``authenticated`` roles it created itself; pre-existing objects
stop the run instead of being dropped, and teardown drops only what this run
created. The harness never provisions a cluster and never connects to the
application database.

The role states matter because Supabase grants new tables to ``anon`` and
``authenticated`` by default (this module reproduces that with
``ALTER DEFAULT PRIVILEGES``). The migration's revoke must remove those grants
one role at a time; ``alembic_version`` keeps them, which proves the default
grants were actually active.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pytest

from tests.pg_harness import (
    ALEMBIC_TIMEOUT_SECONDS,
    HarnessError,
    Target,
    UnsafeTargetError,
    cleanup_owned,
    create_owned_database,
    disposable_cluster_or_skip,
    drop_owned_role,
    ensure_owned_role,
    libpq_free_env,
    preflight_roles_absent,
    psql,
    run_checked,
)

ROOT = Path(__file__).resolve().parents[2]
ROLES = ("anon", "authenticated")
MEMBERSHIP_TABLES = ("memberships", "membership_permission_history")
PLANNER_TABLES = ("planner_posts", "planner_post_activity")
RLS_TABLES = MEMBERSHIP_TABLES + PLANNER_TABLES + (
    "research_reports", "planner_post_origin_sources",
)
AT_0002 = "0002_research_reports"
AT_0003 = "0003_memberships_history"


@dataclass
class OwnedCluster:
    target: Target
    database: str
    roles: list[str] = field(default_factory=list)


@pytest.fixture(scope="module")
def cluster_target() -> Target:
    try:
        target = disposable_cluster_or_skip()
        preflight_roles_absent(target, ROLES)
    except (UnsafeTargetError, HarnessError) as exc:
        pytest.fail(str(exc))
    return target


@pytest.fixture
def owned(cluster_target: Target):
    database = f"trendora_gatea_{uuid4().hex}"
    try:
        create_owned_database(cluster_target, database)
    except (UnsafeTargetError, HarnessError) as exc:
        pytest.fail(str(exc))
    resources = OwnedCluster(target=cluster_target, database=database)
    yield resources
    try:
        cleanup_owned(
            cluster_target, databases=[database], roles=list(resources.roles)
        )
    except HarnessError as exc:
        pytest.fail(str(exc))


def _psql(resources: OwnedCluster, sql: str) -> str:
    return psql(resources.target, sql, dbname=resources.database)


def _alembic(resources: OwnedCluster, *args: str) -> None:
    env = libpq_free_env(os.environ)
    env["DATABASE_URL"] = resources.target.url_for(resources.database)
    try:
        run_checked(
            [sys.executable, "-m", "alembic", *args],
            cwd=ROOT,
            env=env,
            timeout=ALEMBIC_TIMEOUT_SECONDS,
            secrets=resources.target.secrets,
        )
    except HarnessError as exc:
        pytest.fail(str(exc))


def _set_role_state(state: str, resources: OwnedCluster) -> None:
    wanted = {
        "neither": (),
        "anon": ("anon",),
        "authenticated": ("authenticated",),
        "both": ROLES,
    }[state]
    for role in ROLES:
        try:
            if role in wanted:
                ensure_owned_role(resources.target, role, resources.roles)
            else:
                drop_owned_role(resources.target, role, resources.roles)
        except (UnsafeTargetError, HarnessError) as exc:
            pytest.fail(str(exc))


def _grant_defaults(resources: OwnedCluster) -> None:
    """Reproduce Supabase: future tables are granted to anon/authenticated.

    Runs against this run's uniquely named database (default privileges are
    stored per database), as the same role alembic uses.
    """
    for role in ROLES:
        if role in resources.roles:
            _psql(
                resources,
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                f"GRANT ALL ON TABLES TO {role}",
            )


def _present_roles(resources: OwnedCluster) -> list[str]:
    return [role for role in ROLES if role in resources.roles]


def _grant_count(resources: OwnedCluster, table: str) -> str:
    roles = ", ".join(f"'{role}'" for role in ROLES)
    return _psql(
        resources,
        "SELECT count(*) FROM information_schema.role_table_grants "
        f"WHERE table_schema = 'public' AND grantee IN ({roles}) "
        f"AND table_name = '{table}'",
    )


def _rls(resources: OwnedCluster, table: str) -> str:
    return _psql(
        resources,
        f"SELECT relrowsecurity FROM pg_class WHERE relname = '{table}'",
    )


@pytest.mark.parametrize("state", ["neither", "anon", "authenticated", "both"])
def test_revoke_is_per_role_and_rls_is_enabled(state: str, owned: OwnedCluster) -> None:
    _set_role_state(state, owned)
    _grant_defaults(owned)
    _alembic(owned, "upgrade", "head")

    present = _present_roles(owned)
    if present:
        # Canary: without the migration's revoke this would be > 0 too, so a
        # grant on alembic_version proves ALTER DEFAULT PRIVILEGES took effect.
        assert _grant_count(owned, "alembic_version") != "0"
    assert _grant_count(owned, "memberships") == "0"
    assert _grant_count(owned, "membership_permission_history") == "0"
    assert _grant_count(owned, "research_reports") == "0"
    for table in PLANNER_TABLES:
        assert _grant_count(owned, table) == "0"
    assert _grant_count(owned, "planner_post_origin_sources") == "0"
    for table in RLS_TABLES:
        assert _rls(owned, table) == "t", f"{table} must have row level security"
    for role in present:
        for table in RLS_TABLES:
            assert (
                _psql(
                    owned,
                    f"SELECT has_table_privilege('{role}', '{table}', 'SELECT')",
                )
                == "f"
            )


def test_downgrade_preserves_research_reports(owned: OwnedCluster) -> None:
    _set_role_state("both", owned)
    _grant_defaults(owned)
    _alembic(owned, "upgrade", "head")
    _psql(
        owned,
        "INSERT INTO research_reports "
        "(status, topic, markets, source_codes, date_from, date_to, report) "
        "VALUES ('completed', 'gate-a', '[\"SG\"]', '[\"youtube\"]', "
        "'2026-01-01', '2026-01-02', '{}')",
    )
    assert _psql(owned, "SELECT count(*) FROM research_reports") == "1"

    _alembic(owned, "downgrade", AT_0002)

    membership_tables = _psql(
        owned,
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name IN "
        "('memberships', 'membership_permission_history')",
    )
    assert membership_tables == "0"
    assert _rls(owned, "research_reports") == "t", "downgrade must not touch report RLS"
    assert _psql(owned, "SELECT count(*) FROM research_reports") == "1"

    _alembic(owned, "upgrade", "head")

    assert _psql(
        owned,
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name IN "
        "('memberships', 'membership_permission_history')",
    ) == "2"
    for table in RLS_TABLES:
        assert _rls(owned, table) == "t"
    assert _psql(owned, "SELECT count(*) FROM research_reports") == "1"
    assert _grant_count(owned, "memberships") == "0"
    assert _grant_count(owned, "research_reports") == "0"


def _table_count(resources: OwnedCluster, names: tuple[str, ...]) -> str:
    listed = ", ".join(f"'{name}'" for name in names)
    return _psql(
        resources,
        "SELECT count(*) FROM information_schema.tables "
        f"WHERE table_schema = 'public' AND table_name IN ({listed})",
    )


def test_planner_migration_preserves_existing_rows(owned: OwnedCluster) -> None:
    """0003 -> 0007 -> head -> 0003 preserves rows without expiry backfill."""
    _set_role_state("both", owned)
    _grant_defaults(owned)
    _alembic(owned, "upgrade", AT_0003)

    _psql(
        owned,
        "INSERT INTO memberships (user_id, email) VALUES "
        "('00000000-0000-4000-8000-0000000000a0', 'seed@example.com')",
    )
    _psql(
        owned,
        "INSERT INTO membership_permission_history "
        "(actor_id, subject_id, before, after) VALUES "
        "('00000000-0000-4000-8000-0000000000a0', "
        "'00000000-0000-4000-8000-0000000000a0', '{}', '{}')",
    )
    _psql(
        owned,
        "INSERT INTO research_reports "
        "(status, topic, markets, source_codes, date_from, date_to, report) "
        "VALUES ('completed', 'gate-a', '[\"SG\"]', '[\"youtube\"]', "
        "'2026-01-01', '2026-01-02', '{}')",
    )

    _alembic(owned, "upgrade", "0006_planner_research_origin")
    version_width = (
        "SELECT character_maximum_length FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'alembic_version' "
        "AND column_name = 'version_num'"
    )
    assert _psql(owned, version_width) == "32"
    _alembic(owned, "upgrade", "0007_origin_collected_at_nullable")
    assert _psql(owned, version_width) == "64"
    assert _psql(owned, "SELECT version_num FROM alembic_version") == "0007_origin_collected_at_nullable"
    _alembic(owned, "upgrade", "head")

    assert _table_count(owned, PLANNER_TABLES) == "2"
    for table in PLANNER_TABLES:
        assert _rls(owned, table) == "t", f"{table} must have row level security"
        assert _grant_count(owned, table) == "0"
        for role in _present_roles(owned):
            assert (
                _psql(
                    owned,
                    f"SELECT has_table_privilege('{role}', '{table}', 'SELECT')",
                )
                == "f"
            )
    assert _psql(owned, "SELECT count(*) FROM memberships") == "1"
    assert _psql(owned, "SELECT count(*) FROM membership_permission_history") == "1"
    assert _psql(owned, "SELECT count(*) FROM research_reports") == "1"
    assert _psql(owned, "SELECT source_expires_at IS NULL FROM research_reports") == "t"

    _alembic(owned, "downgrade", AT_0003)

    assert _psql(owned, version_width) == "64"
    assert _table_count(owned, PLANNER_TABLES) == "0"
    assert _rls(owned, "research_reports") == "t"
    assert _psql(owned, "SELECT count(*) FROM memberships") == "1"
    assert _psql(owned, "SELECT count(*) FROM membership_permission_history") == "1"
    assert _psql(owned, "SELECT count(*) FROM research_reports") == "1"
