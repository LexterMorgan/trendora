"""Unit tests never touch real I/O.

Guards are installed by ``tests/conftest.py::pytest_configure`` before
collection. This fixture fails any unit test whose recorded unexpected I/O
attempts survive the test body, including attempts whose ``GuardTriggered``
exception application code caught and swallowed.
"""

from __future__ import annotations

import pytest

from tests.io_guards import GUARDS


@pytest.fixture(autouse=True)
def io_guards_per_test() -> None:
    GUARDS.begin_test()
    try:
        yield
        failures = GUARDS.failures()
        if failures:
            pytest.fail(
                "unexpected I/O attempted during unit test "
                "(recorded even though application code may have caught the guard):\n  "
                + "\n  ".join(failures)
            )
    finally:
        GUARDS.end_test()


@pytest.fixture
def supabase_env(monkeypatch):
    """Set SUPABASE_URL / APP_ENV for one test; blank URL means "unset"."""
    from trendora.api.auth import reset_jwks_cache
    from trendora.config import reset_settings_cache

    def configure(supabase_url: str | None, *, app_env: str = "development") -> None:
        monkeypatch.setenv("SUPABASE_URL", supabase_url or "")
        monkeypatch.setenv("APP_ENV", app_env)
        reset_settings_cache()
        reset_jwks_cache()

    yield configure
    reset_settings_cache()
    reset_jwks_cache()
