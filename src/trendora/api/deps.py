"""Shared FastAPI dependencies.

Lives outside ``app.py`` so ``auth`` and ``admin`` can depend on the session
without importing the application module (which imports them back).
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from trendora.api.errors import DataUnavailableError
from trendora.db.session import get_session_factory

_SETUP_MESSAGE = "database session unavailable"


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency: opens a database session for request handlers.

    SQLAlchemy failures while setting the session up become a sanitized 503
    ``data_unavailable``; the underlying exception (which may embed
    connection details) stays in the cause chain, never in the response.
    """
    try:
        session = get_session_factory()()
    except SQLAlchemyError as exc:
        raise DataUnavailableError(_SETUP_MESSAGE) from exc
    try:
        yield session
    finally:
        session.close()
