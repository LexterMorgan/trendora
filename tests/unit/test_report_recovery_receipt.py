"""Synthetic recovery receipts; no keys, providers, or databases are accessed."""

import base64
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from trendora.research.recovery import (
    RecoveryReceiptError,
    RecoveryReceiptExpiredError,
    issue_recovery_receipt,
    verify_recovery_receipt,
)

ACTOR = UUID("00000000-0000-4000-8000-000000000001")
REQUEST = UUID("00000000-0000-4000-8000-000000000002")
FINGERPRINT = "a" * 64
KEY = "fictional-recovery-signing-key-only"
NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)
DEADLINE = NOW + timedelta(days=2)


def _issue(**changes):
    return issue_recovery_receipt(**{
        "actor_id": ACTOR, "request_id": REQUEST, "fingerprint": FINGERPRINT,
        "source_expires_at": DEADLINE, "signing_key": KEY, **changes,
    })


def _verify(receipt, **changes):
    return verify_recovery_receipt(receipt, **{
        "actor_id": ACTOR, "request_id": REQUEST, "fingerprint": FINGERPRINT,
        "now": NOW, "signing_key": KEY, **changes,
    })


def test_receipt_preserves_original_deadline_and_is_stable_for_one_operation():
    receipt = _issue()
    assert receipt == _issue()
    assert _verify(receipt) == DEADLINE
    assert _verify(receipt, now=DEADLINE - timedelta(microseconds=1)) == DEADLINE
    assert receipt != _issue(request_id=ACTOR)


@pytest.mark.parametrize("field,value", [
    ("actor_id", REQUEST), ("request_id", ACTOR), ("fingerprint", "b" * 64),
    ("signing_key", KEY + "other"),
])
def test_receipt_cannot_be_reused_for_another_account_operation_snapshot_or_key(field, value):
    with pytest.raises(RecoveryReceiptError, match="unavailable or invalid"):
        _verify(_issue(), **{field: value})


@pytest.mark.parametrize("field,value", [
    ("version", 2), ("actor_id", str(REQUEST)), ("request_id", str(ACTOR)),
    ("fingerprint", "b" * 64), ("source_expires_at", (DEADLINE + timedelta(days=30)).isoformat()),
])
def test_receipt_claim_tampering_cannot_extend_or_replace_the_original_proof(field, value):
    encoded, signature = _issue().split(".")
    claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    claims[field] = value
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    with pytest.raises(RecoveryReceiptError, match="unavailable or invalid"):
        _verify(f"{forged}.{signature}")


@pytest.mark.parametrize("now", [DEADLINE, DEADLINE + timedelta(microseconds=1)])
def test_receipt_is_expired_at_its_original_deadline(now):
    with pytest.raises(RecoveryReceiptExpiredError, match="has expired"):
        _verify(_issue(), now=now)


@pytest.mark.parametrize("receipt", [None, "", "bad", "x.y.z", "x" * 2049, "☃.signature"])
def test_missing_or_malformed_receipts_have_a_fixed_error(receipt):
    with pytest.raises(RecoveryReceiptError, match="^Recovery receipt is unavailable or invalid\\.$"):
        _verify(receipt)


def test_absent_key_or_source_deadline_does_not_issue_proof():
    assert _issue(signing_key=None) is None
    assert _issue(source_expires_at=None) is None
    with pytest.raises(RecoveryReceiptError):
        _verify(_issue(), signing_key=None)


def test_short_keys_and_naive_dates_cannot_establish_a_deadline():
    with pytest.raises(RecoveryReceiptError):
        _issue(signing_key="short")
    with pytest.raises(RecoveryReceiptError):
        _issue(source_expires_at=DEADLINE.replace(tzinfo=None))
    with pytest.raises(RecoveryReceiptError):
        _verify(_issue(), now=NOW.replace(tzinfo=None))
