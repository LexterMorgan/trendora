"""Dedicated test-database wiring for integration tests.

Resolves only a nonblank ``TRENDORA_TEST_DATABASE_URL`` from the process
environment. Never falls back to ``DATABASE_URL`` or the application
``.env``/settings. Missing or blank test configuration skips every database
integration test. The engine is built from that explicit URL and disposed by
``test_engine``; the application's cached engine is never read or overwritten.

The suite stays deny-by-default: only that engine's dialect may open a
database connection. Ordinary integration tests get no network permission at
all; live smoke fixtures opt into network separately via
``GUARDS.permit_network()`` after their own opt-in checks.

The disposable-cluster opt-in ``TRENDORA_TEST_DISPOSABLE_PG_URL`` gates only
subprocess migrations and destructive shared-data tests. Without it,
``scratch_schema`` returns ``None`` (zero subprocess operations, schema must
already exist) and the ``approved_test_db`` fixture skips tests that
TRUNCATE/commit shared fixture data; ordinary read-only database tests still
run against the explicit pre-migrated ``TRENDORA_TEST_DATABASE_URL``. With
the opt-in, both URLs are validated in-process (supported scheme, no query
options, loopback, same endpoint) before any subprocess starts, execution
uses a canonical URL rebuilt from validated fields with libpq routing
variables stripped from the environment, and failures are credential-redacted.

Destructive shared-data tests run through the ``approved_engine`` fixture:
built from the canonical approved target, rejected before connecting when
inherited libpq overrides (``PGHOSTADDR``, ``PGSERVICE``, any ``PG*`` key)
are present, with no process-environment mutation that could race threaded
tests. Only that engine's dialect may connect while it is alive.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from tests.io_guards import GUARDS
from tests.pg_harness import (
    ALEMBIC_TIMEOUT_SECONDS,
    HarnessError,
    Target,
    UnsafeTargetError,
    alembic_env_if_approved,
    approved_test_target_or_skip,
    require_libpq_clean_env,
    run_checked,
    url_secrets,
)

TEST_DATABASE_URL_ENV = "TRENDORA_TEST_DATABASE_URL"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_test_database_url() -> str | None:
    """Return the explicit test URL from the process env, else ``None``."""
    value = os.environ.get(TEST_DATABASE_URL_ENV)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def build_test_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


def build_approved_engine(
    target: Target, env: Mapping[str, str] | None = None
) -> Engine:
    """Canonical engine for destructive tests, fail closed before connecting.

    The URL is rebuilt from the validated approved target, and inherited
    libpq routing overrides (``PGHOSTADDR``, ``PGSERVICE``, any ``PG*`` key)
    raise ``UnsafeTargetError`` before the engine exists, so no connection
    can be redirected. The process environment is never mutated, which
    would race with threaded tests.
    """
    require_libpq_clean_env(os.environ if env is None else env)
    return build_test_engine(target.url_for(target.database))


@contextmanager
def test_engine_scope(url: str) -> Generator[Engine, None, None]:
    """Build the dedicated engine; only its dialect may connect, then it is disposed.

    ``permit_engine`` is revoked in its own ``finally`` even when the body
    fails, so a failed setup cannot leave a lasting permission behind.
    """
    engine = build_test_engine(url)
    try:
        with GUARDS.permit_engine(engine):
            yield engine
    finally:
        engine.dispose()


def require_test_database_url() -> str:
    """Return the test URL or skip the database integration test clearly."""
    url = resolve_test_database_url()
    if url is None:
        pytest.skip(
            "TRENDORA_TEST_DATABASE_URL is not configured; "
            "database integration tests skipped"
        )
    return url


@pytest.fixture
def test_engine(scratch_schema: str | None) -> Generator[Engine, None, None]:
    """Dedicated engine for the explicit test URL; disposed on teardown.

    Depends on ``scratch_schema`` so an approved run gets the schema migrated
    once per session before any connection. ``scratch_schema`` performs zero
    subprocess work without the disposable-cluster opt-in; the schema must
    already exist in that case (pre-migrated test database).
    """
    with test_engine_scope(require_test_database_url()) as engine:
        yield engine


@pytest.fixture
def db_session(test_engine: Engine) -> Generator[Session, None, None]:
    """Transaction-wrapped session on the test engine; always rolled back."""
    connection = test_engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope="session")
def scratch_schema() -> str | None:
    """Migrate the test database to head once per session, only when approved.

    Alembic runs in a subprocess (the I/O guards do not cover child
    processes), so it requires the owner-approved disposable-cluster opt-in
    ``TRENDORA_TEST_DISPOSABLE_PG_URL``; without that opt-in this fixture
    returns ``None`` and performs zero subprocess operations. With the opt-in,
    both URLs are validated in-process (PostgreSQL scheme, loopback
    resolution, same endpoint) before the subprocess starts, and failure
    output is scrubbed of connection credentials. The application database is
    never touched.
    """
    url = require_test_database_url()
    try:
        env = alembic_env_if_approved(url, os.environ)
    except UnsafeTargetError as exc:
        pytest.fail(str(exc))
    if env is None:
        return None
    try:
        run_checked(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=PROJECT_ROOT,
            env=env,
            timeout=ALEMBIC_TIMEOUT_SECONDS,
            secrets=url_secrets(url),
        )
    except HarnessError as exc:
        pytest.fail(str(exc))
    return url


@pytest.fixture
def approved_test_db() -> Target:
    """Approval gate for tests that TRUNCATE or commit shared fixture data.

    Skips without the disposable-cluster opt-in; fails when the test URL is
    invalid or outside the approved cluster. Read-only database tests do not
    request this fixture and still run on a pre-migrated test database
    without the opt-in. Destructive tests get it transitively through
    ``approved_engine``, which is the only engine they may execute through.
    """
    url = require_test_database_url()
    try:
        return approved_test_target_or_skip(url)
    except UnsafeTargetError as exc:
        pytest.fail(str(exc))


@pytest.fixture
def approved_engine(
    approved_test_db: Target, scratch_schema: str | None
) -> Generator[Engine, None, None]:
    """The one engine destructive shared-data fixtures may execute through.

    Built from the canonical approved target after ``approved_test_db``
    validates it; fails closed (before any connection) when inherited libpq
    routing overrides such as ``PGHOSTADDR`` or ``PGSERVICE`` are present,
    and permits only its own dialect to connect while alive. Destructive
    fixtures and their tests must use this engine instead of ``test_engine``,
    whose psycopg connections would inherit the process environment.
    """
    # Parameter order matters: approval skips before ``scratch_schema`` may
    # run alembic, and the migrated schema exists before any connection.
    try:
        engine = build_approved_engine(approved_test_db)
    except UnsafeTargetError as exc:
        pytest.fail(str(exc))
    try:
        with GUARDS.permit_engine(engine):
            yield engine
    finally:
        engine.dispose()
