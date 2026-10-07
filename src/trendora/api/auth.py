"""Supabase access-token verification and membership authorization (Gate A).

Fail closed everywhere: missing configuration, unreachable JWKS, malformed
keys, undecodable tokens, unknown members, and inactive memberships all
refuse the request. Only RS256/ES256 keys from the project JWKS are
accepted, so an HS256 "secret" token can never be confused for a Supabase
token. ``user_metadata`` claims are never trusted: authorization reads the
local ``memberships`` row.

Tests never install a runtime bypass. ``tests/support/app.py`` overrides the
``require_member`` dependency through FastAPI's own override mechanism, and
only on apps built inside tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any, Callable
from uuid import UUID

import httpx
import jwt
from fastapi import Depends, Request
from jwt.algorithms import ECAlgorithm, RSAAlgorithm
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from trendora.api.deps import get_session
from trendora.api.errors import (
    ApiError,
    AuthForbiddenAdminError,
    AuthInactiveError,
    AuthInvalidTokenError,
    AuthMissingError,
    AuthNotMemberError,
    AuthUnavailableError,
    DataUnavailableError,
)
from trendora.config import get_settings
from trendora.models.membership import Membership

SUPABASE_JWKS_PATH = "/auth/v1/.well-known/jwks.json"
SUPABASE_ISSUER_PATH = "/auth/v1"
SUPABASE_AUDIENCE = "authenticated"
SUPABASE_TOKEN_ROLE = "authenticated"
ALLOWED_JWKS_ALGORITHMS = ("RS256", "ES256")
HTTP_TIMEOUT_SECONDS = 3.0
JWKS_TTL_SECONDS = 600.0
JWKS_REFRESH_MIN_INTERVAL_SECONDS = 60.0
HISTORY_WINDOW_DAYS = 30


@dataclass(frozen=True)
class VerifiedClaims:
    """Claims the verifier proved; ``sub`` is a UUID string."""

    sub: str
    role: str


@dataclass(frozen=True)
class Member:
    """Authorized local membership row."""

    user_id: UUID
    email: str
    active: bool
    is_admin: bool
    can_approve: bool


_cache: dict[str, Any] = {"jwks": None, "at": 0.0, "invalidated_at": None}


def reset_jwks_cache() -> None:
    _cache.update(jwks=None, at=0.0, invalidated_at=None)


def fetch_jwks(supabase_url: str) -> dict[str, Any]:
    """HTTP GET the project JWKS document (no caching here)."""
    response = httpx.get(
        supabase_url + SUPABASE_JWKS_PATH, timeout=HTTP_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response.json()


def get_jwks() -> dict[str, Any]:
    """Cached project JWKS; raises ``AuthUnavailableError`` when unusable."""
    url = get_settings().supabase_url
    if not url:
        raise AuthUnavailableError("SUPABASE_URL is not configured")
    now = monotonic()
    cached = _cache["jwks"]
    if cached is not None and now - _cache["at"] < JWKS_TTL_SECONDS:
        return cached
    try:
        jwks = fetch_jwks(url)
    except Exception as exc:  # noqa: BLE001 - every fetch failure is 503
        raise AuthUnavailableError("could not load Supabase signing keys") from exc
    _cache.update(jwks=jwks, at=monotonic())
    return jwks


def invalidate_jwks() -> bool:
    """Drop cached keys, at most once per ``JWKS_REFRESH_MIN_INTERVAL_SECONDS``."""
    now = monotonic()
    previous = _cache["invalidated_at"]
    if previous is not None and now - previous < JWKS_REFRESH_MIN_INTERVAL_SECONDS:
        return False
    _cache.update(jwks=None, invalidated_at=now)
    return True


def _build_key_map(jwks: object) -> dict[str, tuple[Any, str]]:
    """Map ``kid`` -> (verification key, allowed algorithm); malformed -> 503."""
    if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
        raise AuthUnavailableError("Supabase signing keys are malformed")
    entries = jwks["keys"]
    key_map: dict[str, tuple[Any, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        kid = entry.get("kid")
        alg = entry.get("alg")
        if not isinstance(kid, str) or alg not in ALLOWED_JWKS_ALGORITHMS:
            continue
        try:
            if entry.get("kty") == "RSA":
                key = RSAAlgorithm.from_jwk(json.dumps(entry))
            elif entry.get("kty") == "EC":
                key = ECAlgorithm.from_jwk(json.dumps(entry))
            else:
                continue
        except Exception:  # noqa: BLE001 - unusable key, skip it
            continue
        key_map[kid] = (key, alg)
    if entries and not key_map:
        # Entries exist but none can be used: the document is corrupt, and
        # failing closed beats pretending every token is simply unknown.
        raise AuthUnavailableError("Supabase signing keys are malformed")
    return key_map


def _load_jwks(get_jwks: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return get_jwks()
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001 - key source failure is 503
        raise AuthUnavailableError("could not load Supabase signing keys") from exc


def _resolve_key(token: str, get_jwks: Callable[[], dict[str, Any]]) -> tuple[Any, str]:
    try:
        header = jwt.get_unverified_header(token)
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise AuthInvalidTokenError("access token header is invalid") from exc
    resolved = _build_key_map(_load_jwks(get_jwks)).get(header.get("kid"))
    if resolved is None:
        # Key rotation: refresh the document once, then retry.
        invalidate_jwks()
        resolved = _build_key_map(_load_jwks(get_jwks)).get(header.get("kid"))
    if resolved is None:
        raise AuthInvalidTokenError("access token signing key is unknown")
    return resolved


def verify_access_token(
    token: str,
    *,
    issuer: str,
    audience: str,
    get_jwks: Callable[[], dict[str, Any]],
) -> VerifiedClaims:
    """Verify one Supabase access token; every failure refuses the request."""
    key, algorithm = _resolve_key(token, get_jwks)
    try:
        payload = jwt.decode(
            token,
            key=key,
            algorithms=[algorithm],
            issuer=issuer,
            audience=audience,
            options={"require": ["exp", "sub"]},
        )
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise AuthInvalidTokenError("access token is invalid") from exc
    sub = payload.get("sub")
    if not isinstance(sub, str):
        raise AuthInvalidTokenError("access token subject is missing")
    if payload.get("role") != SUPABASE_TOKEN_ROLE:
        raise AuthInvalidTokenError("access token role is not authenticated")
    return VerifiedClaims(sub=sub, role=payload["role"])


def get_verified_claims(request: Request) -> VerifiedClaims:
    """Read the bearer header and verify it against the project JWKS."""
    scheme, separator, token = request.headers.get("Authorization", "").partition(" ")
    if separator == "" or scheme.lower() != "bearer" or not token.strip():
        raise AuthMissingError("bearer access token is required")
    url = get_settings().supabase_url
    if not url:
        raise AuthUnavailableError("SUPABASE_URL is not configured")
    return verify_access_token(
        token.strip(),
        issuer=url + SUPABASE_ISSUER_PATH,
        audience=SUPABASE_AUDIENCE,
        get_jwks=get_jwks,
    )


def load_member(
    claims: VerifiedClaims = Depends(get_verified_claims),
    session: Session = Depends(get_session),
) -> Member:
    """Resolve the token subject to an active local membership row."""
    try:
        user_id = UUID(claims.sub)
    except (ValueError, TypeError, AttributeError) as exc:
        raise AuthInvalidTokenError("access token subject is not a UUID") from exc
    try:
        row = session.get(Membership, user_id)
    except SQLAlchemyError as exc:
        raise DataUnavailableError("membership lookup failed") from exc
    if row is None:
        raise AuthNotMemberError("no membership exists for this user")
    if not row.active:
        raise AuthInactiveError("membership is inactive")
    return Member(
        user_id=row.user_id,
        email=row.email,
        active=row.active,
        is_admin=row.is_admin,
        can_approve=row.can_approve,
    )


def require_member(
    member: Member = Depends(load_member),
) -> Member:
    """Authenticated, active member identity for protected routes."""
    return member


def require_admin(member: Member = Depends(require_member)) -> Member:
    """Active member with ``is_admin``; 403 ``auth_forbidden_admin`` otherwise."""
    if not member.is_admin:
        raise AuthForbiddenAdminError("administrator access required")
    return member


def get_utc_now() -> datetime:
    """Server clock in UTC; tests override this dependency for frozen time."""
    return datetime.now(timezone.utc)


def report_visible_from(member: Member, now: datetime) -> datetime | None:
    """Oldest report ``created_at`` this member may read; ``None`` = all.

    Rolling window: 30 days inclusive for everyone except admins.
    ``can_approve`` deliberately does not grant full history.
    """
    if member.is_admin:
        return None
    return now - timedelta(days=HISTORY_WINDOW_DAYS)
