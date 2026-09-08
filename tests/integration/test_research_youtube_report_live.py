"""Opt-in live report-pipeline smoke test (M27B).

Cost: ~102 YouTube quota units (one ``search.list`` + one ``videos.list``) plus
exactly **one** real OpenAI-compatible completion (OpenRouter per the developer
``.env``). No retries — a provider 5xx fails the test loudly rather than
re-spending credits. ``result_limit`` is 6, a single market, a single report;
there is deliberately no report matrix.

Gated behind ``TRENDORA_LIVE_SMOKE=1`` plus a resolved YouTube key and a
complete AI provider config, so a normal ``pytest tests/integration`` run skips
this test and spends nothing.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from trendora.api import create_app
from trendora.config import get_settings, reset_settings_cache
from trendora.research.ai_provider import build_ai_provider_config

pytestmark = pytest.mark.integration


def _ai_config_resolved() -> bool:
    reset_settings_cache()
    settings = get_settings()
    try:
        build_ai_provider_config(
            provider=settings.ai_provider,
            model=settings.ai_model,
            endpoint_url=settings.ai_endpoint_url,
            api_key=settings.ai_api_key,
        )
    except Exception:
        return False
    return True


@pytest.fixture(scope="module")
def live_report_client():
    if os.environ.get("TRENDORA_LIVE_SMOKE") != "1":
        pytest.skip(
            "set TRENDORA_LIVE_SMOKE=1 to run the live YouTube report smoke test"
        )
    reset_settings_cache()
    settings = get_settings()
    if not settings.youtube_api_key:
        pytest.skip("YOUTUBE_API_KEY is not configured")
    if not _ai_config_resolved():
        pytest.skip("AI provider configuration is incomplete")
    app = create_app()
    with TestClient(app) as client:
        yield client


def _summary(body: dict) -> dict:
    """Non-sensitive structural summary for assertion-failure messages."""
    refs = body.get("research", {}).get("references", [])
    interp = body.get("interpretation") or {}
    return {
        "status": body.get("status"),
        "error": body.get("error", {}).get("code") if isinstance(body.get("error"), dict) else None,
        "reference_count": len(refs),
        "interpretation_count": len(interp.get("interpretations", [])),
        "first_ref_ids": [r.get("content_external_id") for r in refs[:3]],
    }


class TestLiveReport:
    def test_live_report_completes_with_grounded_citations(self, live_report_client):
        today = date.today()
        response = live_report_client.post(
            "/api/v1/research/report",
            json={
                "topic": "AI education",
                "markets": ["SG"],
                "date_from": (today - timedelta(days=29)).isoformat(),
                "date_to": today.isoformat(),
                "sources": ["youtube"],
                "result_limit": 6,
            },
        )
        if response.status_code != 200:
            body = response.json()
            code = body.get("error", {}).get("code") if isinstance(body.get("error"), dict) else None
            pytest.fail(f"expected 200, got {response.status_code} error={code}")

        body = response.json()
        assert body["status"] in ("completed", "no_evidence"), _summary(body)

        if body["status"] == "no_evidence":
            assert body["research"]["references"] == [], _summary(body)
            assert body["interpretation"] is None, _summary(body)
            assert body["strategy"] is None, _summary(body)
            assert body["ideation"] is None, _summary(body)
            return

        research = body["research"]
        assert research["status"] == "completed", _summary(body)
        references = research["references"]
        assert references, _summary(body)

        # Evidence pack analyses must exactly match the returned references.
        evidence = body["evidence"]
        assert evidence is not None, _summary(body)
        analyses = evidence["analyses"]
        returned_ids = {
            (r["source_code"], r["content_external_id"]) for r in references
        }
        analysis_ids = {
            (a["reference_id"]["source_code"], a["reference_id"]["content_external_id"])
            for a in analyses
        }
        assert analysis_ids == returned_ids, _summary(body)

        # Allowed evidence fields come from the response's own facts, never a
        # hardcoded list.
        allowed_fields = {
            f["field"] for a in analyses for f in a["facts"]
        }

        # Grounded interpretations: non-empty, every item cites non-empty
        # references within the returned set, and fact fields are known fields.
        interpretation = body["interpretation"]
        assert interpretation is not None, _summary(body)
        interpretations = interpretation["interpretations"]
        assert interpretations, _summary(body)
        for item in interpretations:
            citations = item["citations"]
            assert citations, _summary(body)
            for citation in citations:
                kind = citation.get("kind")
                if kind == "pattern":
                    continue
                ref = citation.get("reference")
                assert ref is not None, _summary(body)
                ref_id = (ref["source_code"], ref["content_external_id"])
                assert ref_id in returned_ids, _summary(body)
                if kind == "fact":
                    assert citation["field"] in allowed_fields, _summary(body)

        # AI provenance recorded with non-empty provider/model.
        provenance = interpretation.get("model_provenance")
        if provenance is not None:
            assert provenance.get("provider"), _summary(body)
            assert provenance.get("model"), _summary(body)
