"""Opt-in live multi-market merge verification test (M27C).

Quota cost: one research request over two markets performs one ``search.list``
(100 units) per market plus one ``videos.list`` (1 unit) enrichment — roughly
~204 units total. No retries, a single request, ``result_limit`` 10.

This exercises the real M26C merge path (``_merge_targets``) against live YouTube
data: per-target cap, target-order merge, dedupe by ``(source_code,
content_external_id)``, ``market_contexts`` union for duplicate videos, and
per-source ``source_rank`` reassignment. Real search may legitimately return
**zero** overlapping videos across region codes, so overlap is treated as a
bonus check that runs only when it occurs — its absence never fails the test.

Gated behind ``TRENDORA_LIVE_SMOKE=1`` plus ``YOUTUBE_API_KEY`` so a normal
``pytest tests/integration`` run skips this test and spends nothing.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from trendora.api import create_app
from trendora.config import get_settings, reset_settings_cache

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def live_client():
    if os.environ.get("TRENDORA_LIVE_SMOKE") != "1":
        pytest.skip(
            "set TRENDORA_LIVE_SMOKE=1 to run the live YouTube merge verification test"
        )
    reset_settings_cache()
    if not get_settings().youtube_api_key:
        pytest.skip("YOUTUBE_API_KEY is not configured")
    app = create_app()
    with TestClient(app) as client:
        yield client


def _summary(body: dict) -> dict:
    refs = body.get("references", [])
    return {
        "status": body.get("status"),
        "error": body.get("error", {}).get("code") if isinstance(body.get("error"), dict) else None,
        "reference_count": len(refs),
        "first_ids": [r.get("content_external_id") for r in refs[:3]],
        "ranks": [r.get("source_rank") for r in refs],
    }


class TestLiveMerge:
    def test_multi_market_merge_invariants(self, live_client):
        today = date.today()
        response = live_client.post(
            "/api/v1/research",
            json={
                "topic": "AI education",
                "markets": ["SG", "ID"],
                "date_from": (today - timedelta(days=29)).isoformat(),
                "date_to": today.isoformat(),
                "sources": ["youtube"],
                "result_limit": 10,
            },
        )
        assert response.status_code == 200, _summary(response.json())
        body = response.json()
        assert body["status"] == "completed", _summary(body)
        references = body["references"]

        # Identity uniqueness across the merged list.
        ids = [
            (r["source_code"], r["content_external_id"]) for r in references
        ]
        assert len(ids) == len(set(ids)), _summary(body)

        # Rank integrity: consecutive 1..N for the youtube source, in order.
        youtube = [r for r in references if r["source_code"] == "youtube"]
        ranks = [r["source_rank"] for r in youtube]
        assert ranks == list(range(1, len(youtube) + 1)), _summary(body)

        # Market truthfulness + legacy field sync.
        for reference in references:
            contexts = reference["market_contexts"]
            assert isinstance(contexts, list) and contexts, _summary(body)
            assert set(contexts) <= {"SG", "ID"}, _summary(body)
            if len(contexts) == 1:
                assert reference["market_context"] == contexts[0], _summary(body)
            else:
                assert reference["market_context"] is None, _summary(body)

        # Global limit respected.
        assert len(references) <= 10, _summary(body)

        # Conditional union check: only when cross-market overlap is observed.
        overlapped = [r for r in references if len(r["market_contexts"]) > 1]
        for reference in overlapped:
            codes = reference["market_contexts"]
            # Union preserves selected-market order: a subsequence of ["SG","ID"].
            assert codes == [c for c in ("SG", "ID") if c in codes], _summary(body)
