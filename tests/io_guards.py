"""Guards that record and block unexpected database/network I/O in tests.

Installed once from ``tests/conftest.py::pytest_configure`` before collection.
Four seams are guarded:

* database: ``sqlalchemy.engine.default.DefaultDialect.connect``. psycopg
  connects in C, so a socket patch alone cannot see it.
* network: ``socket.socket.connect`` / ``connect_ex``, covering sync sockets
  and the asyncio/anyio paths used by httpx.
* DNS: ``socket.getaddrinfo``, ``gethostbyname``, ``gethostbyname_ex``.
  Hostnames are blocked before any resolver runs. Numeric hosts and ``None``
  pass through so loopback handling and event-loop mechanics keep working.

Permissions are narrow and kind-specific, never blanket:

* ``permit_engine(engine)`` permits only that engine's dialect: the dedicated
  test engine built from an explicit ``TRENDORA_TEST_DATABASE_URL``.
* ``permit_network()`` permits only network seams, for live provider smoke
  fixtures after their opt-in checks. It never permits database seams.

Each blocked attempt is recorded and raises ``GuardTriggered``. Application
code may catch the exception: the record still fails the owning test
(``tests/unit/conftest.py``), and an attempt no test owns (for example during
collection) fails the whole session in ``tests/conftest.py``. Tests that
intentionally probe the guards wrap the attempt in ``GUARDS.expect_io()``,
which marks it asserted at both the test and session level.

``originals`` exposes the pre-patch implementations so tests can substitute
fakes and prove a seam was (or was not) reached without real I/O.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.engine.default import DefaultDialect


class GuardTriggered(RuntimeError):
    """Raised at a guarded seam; the recorded attempt, not the exception, fails the test."""


def _passes_without_resolver(host: object) -> bool:
    """True when resolution cannot contact a resolver: ``None`` or a numeric IP."""
    if host is None:
        return True
    if not isinstance(host, str):
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


class IOGuards:
    def __init__(self) -> None:
        self.attempts: list[str] = []
        self.expected: list[str] = []
        self.preliminary: list[str] = []
        self.originals: dict[str, object] = {}
        self._checking = False
        self._network_permitted = False
        self._permitted_dialects: list[object] = []
        self._installed = False

    def install(self) -> None:
        """Patch the guarded seams once for the whole session."""
        if self._installed:
            return
        self._installed = True
        self.originals = {
            "dialect.connect": DefaultDialect.connect,
            "socket.connect": socket.socket.connect,
            "socket.connect_ex": socket.socket.connect_ex,
            "getaddrinfo": socket.getaddrinfo,
            "gethostbyname": socket.gethostbyname,
            "gethostbyname_ex": socket.gethostbyname_ex,
        }
        guards = self

        def dialect_connect(dialect, *args, **kwargs):
            guards.note(
                "database",
                f"{getattr(dialect, 'name', 'sqlalchemy')} connect",
                dialect=dialect,
            )
            return guards.originals["dialect.connect"](dialect, *args, **kwargs)  # type: ignore[operator]

        def socket_connect(sock, address):
            guards.note("network", f"connect to {address!r}")
            return guards.originals["socket.connect"](sock, address)  # type: ignore[operator]

        def socket_connect_ex(sock, address):
            guards.note("network", f"connect_ex to {address!r}")
            return guards.originals["socket.connect_ex"](sock, address)  # type: ignore[operator]

        def getaddrinfo(host, port, *args, **kwargs):
            if not _passes_without_resolver(host):
                guards.note("network", f"resolve {host!r}")
            return guards.originals["getaddrinfo"](host, port, *args, **kwargs)  # type: ignore[operator]

        def gethostbyname(host):
            if not _passes_without_resolver(host):
                guards.note("network", f"gethostbyname {host!r}")
            return guards.originals["gethostbyname"](host)  # type: ignore[operator]

        def gethostbyname_ex(host):
            if not _passes_without_resolver(host):
                guards.note("network", f"gethostbyname_ex {host!r}")
            return guards.originals["gethostbyname_ex"](host)  # type: ignore[operator]

        DefaultDialect.connect = dialect_connect
        socket.socket.connect = socket_connect
        socket.socket.connect_ex = socket_connect_ex
        socket.getaddrinfo = getaddrinfo
        socket.gethostbyname = gethostbyname
        socket.gethostbyname_ex = gethostbyname_ex

    def note(self, kind: str, detail: str, *, dialect: object | None = None) -> None:
        """Record one unexpected attempt and block it.

        Returns without recording only for kind-scoped permissions: a
        permitted network attempt under ``permit_network()``, or a permitted
        test-engine dialect under ``permit_engine()``. Recording happens
        before the raise, so application code that catches the exception
        cannot hide the attempt. Attempts made while no test is checking
        (for example during collection) also land in ``preliminary`` and fail
        the session at ``pytest_sessionfinish``.
        """
        if kind == "network" and self._network_permitted:
            return
        if (
            kind == "database"
            and dialect is not None
            and any(d is dialect for d in self._permitted_dialects)
        ):
            return
        message = f"{kind}: {detail}"
        self.attempts.append(message)
        if not self._checking:
            self.preliminary.append(message)
        raise GuardTriggered(
            f"unexpected {kind} attempt blocked by test guard ({detail})"
        )

    @contextmanager
    def permit_network(self) -> Iterator[None]:
        """Permit network seams only; database seams stay blocked.

        For live provider smoke fixtures, entered after their opt-in checks.
        Restores the previous state even when the body fails.
        """
        previous = self._network_permitted
        self._network_permitted = True
        try:
            yield
        finally:
            self._network_permitted = previous

    @contextmanager
    def permit_engine(self, engine: object) -> Iterator[object]:
        """Permit one engine's dialect only (the dedicated test engine).

        Engines without a dialect (fakes) permit nothing. Revokes and is
        exception-safe via ``finally``.
        """
        dialect = getattr(engine, "dialect", None)
        if dialect is not None:
            self._permitted_dialects.append(dialect)
        try:
            yield engine
        finally:
            if dialect is not None:
                self._permitted_dialects[:] = [
                    d for d in self._permitted_dialects if d is not dialect
                ]

    @contextmanager
    def expect_io(self) -> Iterator[None]:
        """Assert guarded attempts inside the block instead of failing anything.

        Moves recorded attempts from both the per-test list and the
        session-level ``preliminary`` list, so an explicitly asserted probe in
        an integration test (where no unit fixture claims attempts) does not
        fail the session either.
        """
        attempts_before = len(self.attempts)
        preliminary_before = len(self.preliminary)
        try:
            yield
        finally:
            moved = self.attempts[attempts_before:]
            del self.attempts[attempts_before:]
            self.expected.extend(moved)
            del self.preliminary[preliminary_before:]

    def begin_test(self) -> None:
        """Claim responsibility for attempt checking; called by the unit autouse fixture."""
        self._checking = True
        self.attempts.clear()
        self.expected.clear()

    def end_test(self) -> None:
        """Release claim so later unowned attempts fail the session instead."""
        self._checking = False

    def failures(self) -> list[str]:
        """Attempts that must fail the running test."""
        return list(self.attempts)


GUARDS = IOGuards()
