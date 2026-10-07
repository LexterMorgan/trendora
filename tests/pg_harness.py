"""Owner-approved disposable PostgreSQL harness for subprocess database work.

Subprocess operations (``psql``, ``alembic``) run only against a cluster the
owner certifies as disposable by setting ``TRENDORA_TEST_DISPOSABLE_PG_URL``.
Without that opt-in the subprocess entry points return ``None`` or
``pytest.skip`` and the caller performs zero subprocess operations. This opt-in
gates subprocess migrations and destructive shared-data tests only; ordinary
read-only database tests do not use it and still run against an explicit,
pre-migrated ``TRENDORA_TEST_DATABASE_URL``. The harness never provisions
clusters and never installs tools.

Every target is validated in-process before any subprocess starts: only the
supported schemes (``postgres``, ``postgresql``, ``postgresql+psycopg``), no
query parameters or fragments (libpq/SQLAlchemy would let ``?host=...`` route
elsewhere), host, port (libpq default 5432 when omitted), and every resolved
address must be loopback. Execution always uses a canonical URL reconstructed
from the validated fields, and subprocess environments are stripped of
inherited libpq routing settings (``PGHOSTADDR``, ``PGSERVICE``, ...) so psql
and Alembic reach the same validated endpoint. Resources get unique names.
Pre-existing databases or roles stop the run instead of being dropped;
cleanup touches only resources this run created. Failure messages are
scrubbed so connection credentials never appear in output; passwords travel
via ``PGPASSWORD``, never argv.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import pytest

ENV_DISPOSABLE_PG_URL = "TRENDORA_TEST_DISPOSABLE_PG_URL"
PSQL_TIMEOUT_SECONDS = 30
ALEMBIC_TIMEOUT_SECONDS = 180

SUPPORTED_SCHEMES = frozenset({"postgres", "postgresql", "postgresql+psycopg"})
_LIBPQ_DEFAULT_PORT = 5432
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_USERINFO = re.compile(r"://[^/@\s]*@")


class UnsafeTargetError(Exception):
    """Refused before any subprocess ran; message is already redacted."""


class HarnessError(Exception):
    """Subprocess failure or timeout; message is already redacted."""


@dataclass(frozen=True)
class Target:
    host: str
    port: int
    user: str
    password: str
    database: str
    ips: frozenset[str]

    @property
    def secrets(self) -> tuple[str, ...]:
        return tuple(s for s in (self.password, self.user) if s)

    def url_for(self, dbname: str) -> str:
        auth = quote_userinfo(self.user, self.password)
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"postgresql+psycopg://{auth}{host}:{self.port}/{dbname}"


def quote_userinfo(user: str, password: str) -> str:
    if not user and not password:
        return ""
    if not password:
        return f"{quote(user, safe='')}@"
    return f"{quote(user, safe='')}:{quote(password, safe='')}@"


def url_secrets(url: str) -> tuple[str, ...]:
    """Raw and URL-encoded user/password from a URL, for redaction."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ()
    found: list[str] = []
    for value in (parts.password, parts.username):
        if not value:
            continue
        raw = unquote(value)
        found.append(raw)
        encoded = quote(raw, safe="")
        if encoded != raw:
            found.append(encoded)
    return tuple(found)


def _scrub(text: str, secrets: Sequence[str]) -> str:
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, "[redacted]")
    return _USERINFO.sub("://[redacted]@", out)


def resolve_disposable_pg_url() -> str | None:
    value = os.environ.get(ENV_DISPOSABLE_PG_URL)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _resolve_ips(host: str, port: int) -> frozenset[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return frozenset(entry[4][0].split("%")[0] for entry in infos)


def validate_target(url: str) -> Target:
    """Parse and validate a target URL in-process; raises UnsafeTargetError.

    Rejects unsupported schemes and any query/fragment before resolving
    anything: query parameters such as ``?host=...&port=...`` change the
    effective connection target in both libpq and SQLAlchemy, so only a URL
    whose routing comes from its validated fields is accepted.
    """
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise UnsafeTargetError(f"target URL cannot be parsed: {exc}") from None
    scheme = parts.scheme.lower()
    if scheme not in SUPPORTED_SCHEMES:
        raise UnsafeTargetError(
            f"target URL scheme {scheme!r} is not a supported PostgreSQL "
            f"scheme (allowed: {', '.join(sorted(SUPPORTED_SCHEMES))})"
        )
    if parts.query:
        raise UnsafeTargetError(
            "target URL carries query parameters; connection options in query "
            "strings can change the effective host or port and are refused "
            "(rebuild the URL from scheme, host, port, user, password, and "
            "database only)"
        )
    if parts.fragment:
        raise UnsafeTargetError(
            "target URL carries a fragment; fragments are refused for "
            "disposable-harness URLs"
        )
    host = parts.hostname
    if not host:
        raise UnsafeTargetError("target URL has no host")
    try:
        port = parts.port or _LIBPQ_DEFAULT_PORT
    except ValueError:
        raise UnsafeTargetError("target URL has an invalid port") from None
    try:
        ips = _resolve_ips(host, port)
    except socket.gaierror as exc:
        reason = exc.strerror or str(exc)
        raise UnsafeTargetError(
            f"cannot resolve target host {host!r}: {reason}"
        ) from None
    if not ips or not all(ipaddress.ip_address(ip).is_loopback for ip in ips):
        raise UnsafeTargetError(
            f"target host {host!r} does not resolve exclusively to loopback "
            "addresses; refusing to run subprocess database work there"
        )
    return Target(
        host=host,
        port=port,
        user=unquote(parts.username or ""),
        password=unquote(parts.password or ""),
        database=parts.path.lstrip("/") or "postgres",
        ips=ips,
    )


def disposable_target_or_none() -> Target | None:
    """Approved and validated cluster target, or ``None`` when not approved."""
    url = resolve_disposable_pg_url()
    if url is None:
        return None
    return validate_target(url)


def disposable_cluster_or_skip() -> Target:
    """Approved cluster target, or skip the test with zero subprocess work."""
    url = resolve_disposable_pg_url()
    if url is None:
        pytest.skip(
            f"{ENV_DISPOSABLE_PG_URL} is not set; tests needing a disposable "
            "PostgreSQL cluster are skipped (roles are cluster-wide)"
        )
    return validate_target(url)


def _same_endpoint(a: Target, b: Target) -> bool:
    return a.port == b.port and bool(a.ips & b.ips)


def libpq_free_env(env: Mapping[str, str]) -> dict[str, str]:
    """Inherited environment minus libpq routing settings.

    ``PGHOSTADDR``, ``PGSERVICE``, ``PGHOST``, and friends would redirect the
    approved target even when host and port are pinned on the command line or
    in the URL, so they are never inherited. ``PGPASSWORD`` is re-added
    explicitly by :func:`psql` from the validated target only.
    """
    return {key: value for key, value in env.items() if not key.startswith("PG")}


def libpq_routing_overrides(env: Mapping[str, str]) -> list[str]:
    """Inherited ``PG*`` keys libpq could use to reroute a connection."""
    return sorted(key for key in env if key.startswith("PG"))


def require_libpq_clean_env(env: Mapping[str, str]) -> None:
    """Fail closed when inherited libpq routing overrides are present.

    An in-process engine cannot strip them without mutating the process
    environment, which would race with threaded tests, so they are rejected
    before any connection instead. Only key names appear in the message;
    values may hold credentials.
    """
    found = libpq_routing_overrides(env)
    if found:
        raise UnsafeTargetError(
            "inherited libpq environment overrides ("
            + ", ".join(found)
            + ") could redirect the approved target; unset them before "
            "destructive database tests"
        )


def _approved_test_target(test_url: str) -> Target | None:
    """Validated test target inside the approved cluster, or ``None``.

    Raises UnsafeTargetError when the opt-in exists but the test URL is
    invalid or points outside the approved cluster, before any subprocess.
    """
    cluster = disposable_target_or_none()
    if cluster is None:
        return None
    test_target = validate_target(test_url)
    if not _same_endpoint(test_target, cluster):
        raise UnsafeTargetError(
            "TRENDORA_TEST_DATABASE_URL does not point at the same loopback "
            "endpoint as the approved disposable cluster; refusing"
        )
    return test_target


def alembic_env_if_approved(
    test_url: str, base_env: Mapping[str, str]
) -> dict[str, str] | None:
    """Environment for an alembic subprocess, or ``None`` when not approved.

    With the opt-in present, both the approved cluster and the test URL are
    validated and must share one endpoint; anything else raises
    UnsafeTargetError before any subprocess would run. The returned
    ``DATABASE_URL`` is a canonical URL reconstructed from the validated
    fields (query-free, supported scheme), and the environment has inherited
    libpq routing settings stripped, so Alembic connects to exactly the
    endpoint psql uses.
    """
    target = _approved_test_target(test_url)
    if target is None:
        return None
    return {
        **libpq_free_env(base_env),
        "DATABASE_URL": target.url_for(target.database),
    }


def approved_test_target_or_skip(test_url: str) -> Target:
    """Validated test target inside the approved cluster, else skip.

    Required by tests that TRUNCATE or commit shared fixture data: without
    the disposable-cluster opt-in they skip instead of mutating a shared
    database.
    """
    target = _approved_test_target(test_url)
    if target is None:
        pytest.skip(
            f"{ENV_DISPOSABLE_PG_URL} is not set; destructive shared-data "
            "tests require disposable-target approval"
        )
    return target


def _run_subprocess(
    argv: Sequence[str],
    *,
    timeout: int,
    env: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(argv),
        cwd=cwd,
        env=dict(env) if env is not None else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def run_checked(
    argv: Sequence[str],
    *,
    timeout: int,
    env: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
    secrets: Sequence[str] = (),
) -> str:
    """Run one subprocess with a timeout; return stdout or raise HarnessError.

    stdout/stderr (including timeout partials) pass through ``secrets``
    redaction, so credentials embedded in command output never surface.
    """
    executable = Path(argv[0]).name if argv else "?"
    try:
        result = _run_subprocess(argv, timeout=timeout, env=env, cwd=cwd)
    except subprocess.TimeoutExpired as exc:
        partial_out = _decode(exc.output)
        partial_err = _decode(exc.stderr)
        raise HarnessError(
            _scrub(
                f"command timed out after {timeout}s: {executable}\n"
                f"stdout:\n{partial_out}\nstderr:\n{partial_err}",
                secrets,
            )
        ) from None
    except FileNotFoundError:
        raise HarnessError(f"required executable not found: {executable}") from None
    if result.returncode != 0:
        raise HarnessError(
            _scrub(
                f"command failed (exit {result.returncode}): {executable}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
                secrets,
            )
        )
    return result.stdout


def _decode(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _check_identifier(name: str, kind: str) -> None:
    if not _IDENTIFIER.match(name):
        raise UnsafeTargetError(f"{kind} name {name!r} is not a plain lowercase identifier")


def psql(target: Target, sql: str, *, dbname: str | None = None) -> str:
    """Run one SQL statement via psql against a validated target."""
    argv = ["psql", "-h", target.host, "-p", str(target.port)]
    if target.user:
        argv += ["-U", target.user]
    argv += [
        "-d",
        dbname or target.database,
        "-v",
        "ON_ERROR_STOP=1",
        "-tAc",
        sql,
    ]
    env = libpq_free_env(os.environ)
    if target.password:
        env["PGPASSWORD"] = target.password
    out = run_checked(
        argv, timeout=PSQL_TIMEOUT_SECONDS, env=env, secrets=target.secrets
    )
    return out.strip()


def role_exists(target: Target, role: str) -> bool:
    _check_identifier(role, "role")
    return (
        psql(
            target,
            "SELECT count(*) FROM pg_roles WHERE rolname = "
            f"'{role}'",
        )
        != "0"
    )


def preflight_roles_absent(target: Target, roles: Sequence[str]) -> None:
    """Stop before any mutation when a cluster role already exists."""
    for role in roles:
        if role_exists(target, role):
            raise UnsafeTargetError(
                f"role {role!r} already exists in the disposable cluster; "
                "refusing to modify pre-existing roles"
            )


def create_owned_database(target: Target, name: str) -> None:
    _check_identifier(name, "database")
    exists = psql(
        target,
        "SELECT count(*) FROM pg_database WHERE datname = " f"'{name}'",
    )
    if exists != "0":
        raise UnsafeTargetError(
            f"database {name!r} already exists; refusing to drop or reuse a "
            "pre-existing database"
        )
    psql(target, f'CREATE DATABASE "{name}"')


def ensure_owned_role(target: Target, role: str, owned_roles: list[str]) -> None:
    _check_identifier(role, "role")
    if role in owned_roles:
        return
    if role_exists(target, role):
        raise UnsafeTargetError(
            f"role {role!r} already exists; refusing to modify pre-existing roles"
        )
    psql(target, f'CREATE ROLE "{role}"')
    owned_roles.append(role)


def drop_owned_role(target: Target, role: str, owned_roles: list[str]) -> None:
    _check_identifier(role, "role")
    if role not in owned_roles:
        if role_exists(target, role):
            raise UnsafeTargetError(
                f"role {role!r} was not created by this run; refusing to drop "
                "a pre-existing role"
            )
        return
    psql(target, f'DROP ROLE "{role}"')
    owned_roles.remove(role)


def cleanup_owned(
    target: Target, *, databases: Sequence[str] = (), roles: Sequence[str] = ()
) -> None:
    """Drop only the databases and roles this run created, in safe order."""
    for name in databases:
        _check_identifier(name, "database")
        psql(target, f'DROP DATABASE "{name}" WITH (FORCE)')
    for role in roles:
        _check_identifier(role, "role")
        psql(target, f'DROP ROLE "{role}"')
