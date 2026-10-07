"""Signed recovery evidence outside the immutable report snapshot."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from uuid import UUID


class RecoveryReceiptError(ValueError):
    """A receipt cannot establish the original server retention deadline."""


class RecoveryReceiptExpiredError(RecoveryReceiptError):
    """An authentic receipt has reached its original deadline."""


def _key(value: str | None) -> bytes:
    if not isinstance(value, str) or len(value.encode("utf-8")) < 32:
        raise RecoveryReceiptError("Recovery receipt is unavailable or invalid.")
    return value.encode("utf-8")


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise RecoveryReceiptError("Recovery receipt is unavailable or invalid.")
    return value.astimezone(timezone.utc)


def issue_recovery_receipt(
    *, actor_id: UUID, request_id: UUID, fingerprint: str,
    source_expires_at: datetime | None, signing_key: str | None,
) -> str | None:
    if signing_key is None or source_expires_at is None:
        return None
    claims = {
        "version": 1,
        "actor_id": str(actor_id),
        "request_id": str(request_id),
        "fingerprint": fingerprint,
        "source_expires_at": _utc(source_expires_at).isoformat(),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=")
    signature = hmac.new(_key(signing_key), encoded, hashlib.sha256).hexdigest()
    return f"{encoded.decode('ascii')}.{signature}"


def verify_recovery_receipt(
    receipt: str | None, *, actor_id: UUID, request_id: UUID, fingerprint: str,
    signing_key: str | None, now: datetime,
) -> datetime:
    try:
        if not isinstance(receipt, str) or len(receipt) > 2048:
            raise ValueError
        encoded, signature = receipt.split(".")
        expected = hmac.new(_key(signing_key), encoded.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        claims = json.loads(base64.b64decode(
            encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True,
        ))
        if not isinstance(claims, dict) or set(claims) != {
            "version", "actor_id", "request_id", "fingerprint", "source_expires_at",
        }:
            raise ValueError
        if (type(claims["version"]) is not int or claims["version"] != 1
                or claims["actor_id"] != str(actor_id)
                or claims["request_id"] != str(request_id)
                or claims["fingerprint"] != fingerprint):
            raise ValueError
        deadline = _utc(datetime.fromisoformat(claims["source_expires_at"]))
        current = _utc(now)
    except (ValueError, TypeError, KeyError):
        raise RecoveryReceiptError("Recovery receipt is unavailable or invalid.") from None
    if deadline <= current:
        raise RecoveryReceiptExpiredError("Recovery receipt has expired.")
    return deadline
