"""Pytest configuration."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "integration: requires a configured PostgreSQL DATABASE_URL"
    )
