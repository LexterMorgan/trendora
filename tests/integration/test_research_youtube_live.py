"""Opt-in live YouTube smoke test for the research API (M27A).

Quota cost: each research request performs one ``search.list`` (100 units) plus
one ``videos.list`` (1 unit) — roughly ~102 units per test, ~204 units per run.
Two tests, ``result_limit`` capped at 6, no retries, no report/AI calls, no
extra runs in fixtures.

These tests hit the real YouTube Data API v3 and therefore spend quota. They are
gated behind ``TRENDORA_LIVE_SMOKE=1`` plus a configured ``YOUTUBE_API_KEY`` so a
normal ``pytest tests/integration`` run never spends quota by accident. Without
the gate they are skipped.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from trendora.api import create_app
from trendora.config import get_settings, reset_settings_cache

pytestmark = pytest.mark.integration


def _live_key() -> str | None:
    """Return a YouTube API key for the smoke test, or ``None`` when gated off."""
    if os.environ.get("TRENDORA_LIVE_SMOKE") != "1":
        return None
    reset_settings_cache()
    key = get_settings().youtube_api_key
    return key if key else None


@pytest.fixture(scope="module")
def live_client():
    key = _live_key()
    if key is None:
        pytest.skip(
            "set TRENDORA_LIVE_SMOKE=1 and YOUTUBE_API_KEY to run the live YouTube smoke test"
        )
    app = create_app()
    with TestClient(app) as client:
        yield client


def _payload(markets: list[str], *, singular: bool) -> dict:
    today = date.today()
    body = {
        "topic": "AI education",
        "date_from": (today - timedelta(days=29)).isoformat(),
        "date_to": today.isoformat(),
        "sources": ["youtube"],
        "result_limit": 6,
    }
    if singular:
        body["market"] = markets[0]
    else:
        body["markets"] = markets
    return body


def _summary(body: dict) -> dict:
    """Non-sensitive structural summary for assertion-failure messages."""
    refs = body.get("references", [])
    return {
        "status": body.get("status"),
        "error": body.get("error", {}).get("code") if isinstance(body.get("error"), dict) else None,
        "reference_count": len(refs),
        "first_ids": [ref.get("content_external_id") for ref in refs[:3]],
    }


class TestLiveSingleMarket:
    def test_single_market_completes_with_market_contexts(self, live_client):
        response = live_client.post(
            "/api/v1/research", json=_payload(["SG"], singular=True)
        )
        assert response.status_code == 200, _summary(response.json())
        body = response.json()
        assert body["status"] == "completed", _summary(body)
        assert body["query"]["markets"] == ["SG"], _summary(body)
        assert body["query"]["market"] == "SG", _summary(body)
        assert body["executed_sources"] == ["youtube"], _summary(body)
        for reference in body["references"]:
            assert reference["market_contexts"] == ["SG"], _summary(body)
            assert reference["market_context"] == "SG", _summary(body)


class TestLiveMultiMarket:
    def test_multi_market_completes_with_market_context_subsets(self, live_client):
        response = live_client.post(
            "/api/v1/research", json=_payload(["SG", "ID"], singular=False)
        )
        assert response.status_code == 200, _summary(response.json())
        body = response.json()
        assert body["status"] == "completed", _summary(body)
        assert body["query"]["markets"] == ["SG", "ID"], _summary(body)
        assert body["query"]["market"] is None, _summary(body)
        assert body["executed_sources"] == ["youtube"], _summary(body)
        for reference in body["references"]:
            contexts = reference["market_contexts"]
            assert isinstance(contexts, list) and contexts, _summary(body)
            assert set(contexts) <= {"SG", "ID"}, _summary(body)
            metrics = reference["metrics"]
            assert set(metrics) == {
                "view_count",
                "like_count",
                "comment_count",
                "reaction_count",
                "share_count",
            }, _summary(body)
