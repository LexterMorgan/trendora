"""Gate A: real access-token verification against locally signed JWTs.

No network and no Supabase: signing keys are generated in-process and the
JWKS source is a stub. Covers claim validation, algorithm constraints, key
rotation hooks, and the JWKS fetch/cache seams.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from trendora.api.auth import (
    ALLOWED_JWKS_ALGORITHMS,
    JWKS_REFRESH_MIN_INTERVAL_SECONDS,
    JWKS_TTL_SECONDS,
    get_jwks,
    invalidate_jwks,
    reset_jwks_cache,
    verify_access_token,
)
from trendora.api.errors import AuthInvalidTokenError, AuthUnavailableError

ISSUER = "https://example.supabase.co/auth/v1"
AUDIENCE = "authenticated"


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def ec_key():
    return ec.generate_private_key(ec.SECP256R1())


def _jwk(public_key: Any, *, kid: str, alg: str) -> dict[str, Any]:
    cls = RSAAlgorithm if alg == "RS256" else ECAlgorithm
    jwk = json.loads(cls.to_jwk(public_key))
    jwk.update(kid=kid, alg=alg, use="sig")
    return jwk


def _claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(uuid.uuid4()),
        "role": "authenticated",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 300,
    }
    payload.update(overrides)
    return payload


def _sign(payload: dict[str, Any], key: Any, algorithm: str, *, kid: str = "k1") -> str:
    return jwt.encode(payload, key, algorithm=algorithm, headers={"kid": kid})


def _b64(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def _structural_token(*, kid: str = "k1", alg: str = "RS256") -> str:
    """Token whose header parses but whose signature was never produced."""
    header = _b64(json.dumps({"alg": alg, "typ": "JWT", "kid": kid}).encode())
    payload = _b64(json.dumps(_claims()).encode())
    return f"{header.decode()}.{payload.decode()}.c2ln"


def _verify(token: str, get_jwks_stub=None):
    stub = get_jwks_stub or (lambda: {"keys": []})
    return verify_access_token(
        token, issuer=ISSUER, audience=AUDIENCE, get_jwks=stub
    )


class TestValidTokens:
    def test_rs256_token_verifies(self, rsa_key) -> None:
        jwks = {"keys": [_jwk(rsa_key.public_key(), kid="k1", alg="RS256")]}
        claims = _claims()
        token = _sign(claims, rsa_key, "RS256")
        result = _verify(token, lambda: jwks)
        assert result.sub == claims["sub"]
        assert result.role == "authenticated"

    def test_es256_token_verifies(self, ec_key) -> None:
        jwks = {"keys": [_jwk(ec_key.public_key(), kid="k1", alg="ES256")]}
        claims = _claims()
        token = _sign(claims, ec_key, "ES256")
        result = _verify(token, lambda: jwks)
        assert result.sub == claims["sub"]

    def test_audience_list_form_verifies(self, rsa_key) -> None:
        jwks = {"keys": [_jwk(rsa_key.public_key(), kid="k1", alg="RS256")]}
        token = _sign(_claims(aud=["authenticated", "other"]), rsa_key, "RS256")
        result = _verify(token, lambda: jwks)
        assert result.sub is not None

    def test_algorithms_tuple_allows_only_rs_and_es(self) -> None:
        assert ALLOWED_JWKS_ALGORITHMS == ("RS256", "ES256")


class TestRejectedTokens:
    @pytest.mark.parametrize(
        "override",
        [
            {"exp": int(time.time()) - 10},
            {"iss": "https://evil.example.com/auth/v1"},
            {"aud": "anon"},
            {"role": "service_role"},
            {"sub": None},
            {"exp": None},
        ],
        ids=["expired", "wrong_issuer", "aud_anon", "role_service_role", "null_sub", "null_exp"],
    )
    def test_claim_failures_rejected(self, rsa_key, override) -> None:
        jwks = {"keys": [_jwk(rsa_key.public_key(), kid="k1", alg="RS256")]}
        token = _sign(_claims(**override), rsa_key, "RS256")
        with pytest.raises(AuthInvalidTokenError):
            _verify(token, lambda: jwks)

    def test_missing_sub_rejected(self, rsa_key) -> None:
        payload = _claims()
        del payload["sub"]
        jwks = {"keys": [_jwk(rsa_key.public_key(), kid="k1", alg="RS256")]}
        with pytest.raises(AuthInvalidTokenError):
            _verify(_sign(payload, rsa_key, "RS256"), lambda: jwks)

    def test_missing_exp_rejected(self, rsa_key) -> None:
        payload = _claims()
        del payload["exp"]
        jwks = {"keys": [_jwk(rsa_key.public_key(), kid="k1", alg="RS256")]}
        with pytest.raises(AuthInvalidTokenError):
            _verify(_sign(payload, rsa_key, "RS256"), lambda: jwks)

    def test_alg_none_rejected(self, rsa_key) -> None:
        jwks = {"keys": [_jwk(rsa_key.public_key(), kid="k1", alg="RS256")]}
        token = (
            _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
            + b"."
            + _b64(json.dumps(_claims()).encode())
            + b"."
        ).decode()
        with pytest.raises(AuthInvalidTokenError):
            _verify(token, lambda: jwks)

    def test_hs256_token_rejected(self) -> None:
        token = _sign(_claims(), "super-secret", "HS256")
        with pytest.raises(AuthInvalidTokenError):
            _verify(token, lambda: {"keys": []})

    def test_wrong_key_rejected(self, rsa_key) -> None:
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwks = {"keys": [_jwk(other.public_key(), kid="k1", alg="RS256")]}
        token = _sign(_claims(), rsa_key, "RS256")
        with pytest.raises(AuthInvalidTokenError):
            _verify(token, lambda: jwks)

    def test_garbage_token_rejected(self) -> None:
        with pytest.raises(AuthInvalidTokenError):
            _verify("not.a.jwt")

    def test_unknown_kid_refetches_once_then_rejects(self, rsa_key) -> None:
        jwks = {"keys": [_jwk(rsa_key.public_key(), kid="k1", alg="RS256")]}
        calls: list[int] = []

        def stub() -> dict[str, Any]:
            calls.append(1)
            return jwks

        token = _sign(_claims(), rsa_key, "RS256", kid="rotated-away")
        with pytest.raises(AuthInvalidTokenError):
            _verify(token, stub)
        assert len(calls) == 2


class TestUnavailableKeySource:
    def test_fetch_failure_becomes_auth_unavailable(self) -> None:
        def stub() -> dict[str, Any]:
            raise httpx.ConnectError("jwks down")

        with pytest.raises(AuthUnavailableError):
            _verify(_structural_token(), stub)

    def test_auth_unavailable_propagates(self) -> None:
        def stub() -> dict[str, Any]:
            raise AuthUnavailableError("no SUPABASE_URL")

        with pytest.raises(AuthUnavailableError):
            _verify(_structural_token(), stub)

    @pytest.mark.parametrize("bad", ["not-a-dict", {"keys": "nope"}, {"keys": [1]}])
    def test_malformed_jwks_is_unavailable(self, bad) -> None:
        with pytest.raises(AuthUnavailableError):
            _verify(_structural_token(), lambda: bad)


class TestJWKSCache:
    @pytest.fixture(autouse=True)
    def _clean_cache(self, supabase_env):
        supabase_env("https://example.supabase.co")
        reset_jwks_cache()
        yield
        reset_jwks_cache()

    @staticmethod
    def _counting_fetch(monkeypatch, payload=None, calls=None):
        calls = calls if calls is not None else []

        def fake_fetch(url: str) -> dict[str, Any]:
            calls.append(url)
            return payload if payload is not None else {"keys": []}

        monkeypatch.setattr("trendora.api.auth.fetch_jwks", fake_fetch)
        return calls

    @staticmethod
    def _freeze_clock(monkeypatch, start: float) -> list[float]:
        clock = [start]
        monkeypatch.setattr("trendora.api.auth.monotonic", lambda: clock[0])
        return clock

    def test_fetches_once_until_ttl_expires(self, monkeypatch) -> None:
        calls = self._counting_fetch(monkeypatch)
        clock = self._freeze_clock(monkeypatch, 1000.0)
        get_jwks()
        clock[0] += JWKS_TTL_SECONDS - 1
        get_jwks()
        assert len(calls) == 1
        clock[0] += 2
        get_jwks()
        assert len(calls) == 2

    def test_invalidate_refetches_and_rate_limits(self, monkeypatch) -> None:
        calls = self._counting_fetch(monkeypatch)
        self._freeze_clock(monkeypatch, 5000.0)
        get_jwks()
        assert len(calls) == 1
        assert invalidate_jwks() is True
        get_jwks()
        assert len(calls) == 2
        assert invalidate_jwks() is False
        get_jwks()
        assert len(calls) == 2

    def test_invalidate_expires_after_min_interval(self, monkeypatch) -> None:
        calls = self._counting_fetch(monkeypatch)
        clock = self._freeze_clock(monkeypatch, 0.0)
        get_jwks()
        assert invalidate_jwks() is True
        clock[0] += JWKS_REFRESH_MIN_INTERVAL_SECONDS + 1
        assert invalidate_jwks() is True
        get_jwks()
        assert len(calls) == 2

    def test_missing_supabase_url_is_unavailable(self, supabase_env) -> None:
        supabase_env(None)
        with pytest.raises(AuthUnavailableError):
            get_jwks()

    def test_fetch_failure_wrapped_as_unavailable(self, monkeypatch) -> None:
        def boom(url: str) -> dict[str, Any]:
            raise httpx.ConnectError("nope")

        monkeypatch.setattr("trendora.api.auth.fetch_jwks", boom)
        with pytest.raises(AuthUnavailableError):
            get_jwks()


class TestFetchJWKS:
    def test_builds_jwks_url_with_timeout(self, monkeypatch) -> None:
        import trendora.api.auth as auth_module

        seen: list[tuple[str, float]] = []

        class _Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return {"keys": []}

        def fake_get(url: str, *, timeout: float):
            seen.append((url, timeout))
            return _Response()

        monkeypatch.setattr(auth_module.httpx, "get", fake_get)
        jwks = auth_module.fetch_jwks("https://example.supabase.co")
        assert jwks == {"keys": []}
        assert seen == [
            ("https://example.supabase.co/auth/v1/.well-known/jwks.json", 3.0)
        ]
