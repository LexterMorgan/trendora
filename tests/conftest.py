"""Pytest configuration."""

import sys

import pytest
from _pytest.config import ExitCode

from tests.io_guards import GUARDS


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "integration: requires a configured PostgreSQL DATABASE_URL"
    )
    # Active before any test collection: unexpected I/O during import fails loudly.
    GUARDS.install()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # Attempts no test claimed (collection, --collect-only, zero-test runs)
    # were swallowed there; failing the session here keeps them visible.
    if GUARDS.preliminary:
        session.exitstatus = ExitCode.TESTS_FAILED
        sys.stderr.write(
            "unexpected I/O recorded outside any test:\n  "
            + "\n  ".join(GUARDS.preliminary)
            + "\n"
        )
