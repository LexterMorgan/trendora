"""Load project `.env` for integration tests the same way application settings do.

Skip checks previously looked only at `os.environ`, so a valid `DATABASE_URL` in
`.env` was treated as missing. Unit tests do not load this conftest.
"""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from trendora.config import get_settings, reset_settings_cache


def resolve_database_url() -> str | None:
    """Return a database URL from the process env or application `.env` settings."""

    for key in ("TRENDORA_TEST_DATABASE_URL", "DATABASE_URL"):
        value = os.environ.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    reset_settings_cache()
    try:
        return get_settings().database_url
    except ValidationError:
        reset_settings_cache()
        return None


@pytest.fixture
def database_url() -> str:
    url = resolve_database_url()
    if not url:
        pytest.skip("DATABASE_URL is not configured")
    return url
