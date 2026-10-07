"""Explicit authentication overrides for tests that do not exercise auth.

``create_test_app`` builds the real app and registers FastAPI dependency
overrides for ``require_member`` only. There is no runtime bypass in
``trendora``: production code always runs the full verification chain.
Auth-specific tests must build their own app with ``trendora.api.create_app``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from fastapi import FastAPI

from trendora.api import create_app
from trendora.api.auth import Member, require_member

TEST_MEMBER = Member(
    user_id=UUID("00000000-0000-4000-8000-000000000001"),
    email="tester@example.com",
    active=True,
    is_admin=False,
    can_approve=False,
)

ADMIN_MEMBER = Member(
    user_id=UUID("00000000-0000-4000-8000-000000000002"),
    email="admin@example.com",
    active=True,
    is_admin=True,
    can_approve=False,
)


class FakeSession:
    """Stand-in for the DB session dependency: one row, or one error."""

    def __init__(self, row: Any = None, error: Exception | None = None) -> None:
        self.row = row
        self.error = error

    def get(self, model: object, pk: object) -> Any:
        if self.error is not None:
            raise self.error
        return self.row

    def close(self) -> None:  # pragma: no cover - dependency teardown only
        return None


def membership_row(
    user_id: UUID,
    *,
    email: str = "row@example.com",
    active: bool = True,
    is_admin: bool = False,
    can_approve: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        email=email,
        active=active,
        is_admin=is_admin,
        can_approve=can_approve,
    )


def create_test_app(member: Member | None = None) -> FastAPI:
    """App with ``require_member`` overridden to a fixed member identity.

    ``require_admin`` runs its real authority check against the overridden
    member, so pass ``ADMIN_MEMBER`` for admin-route success tests.
    """
    app = create_app()
    resolved = member if member is not None else TEST_MEMBER
    app.dependency_overrides[require_member] = lambda: resolved
    return app
