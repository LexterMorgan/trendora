"""Request-local diagnostics use fictional traffic and never become evidence."""

import json

import httpx
import pytest

from trendora.research.run_details import (
    collect_run_details, measure_stage, record_retry,
)
from trendora.research.ai_provider import _post_chat_request
from tests.unit.test_research_ai_provider import _config
from tests.unit.test_research_report_api import _app_with_report_service, _payload, PATH
from tests.unit.test_research_reporting import _report_service
from trendora.api.app import _snapshot_projection
from trendora.api.research_report_models import ResearchReportResponse
from trendora.api.report_snapshot import snapshot_fingerprint


@pytest.fixture(autouse=True)
def _mock_report_persistence(monkeypatch) -> None:
    """Keep the API test offline: no database, no credentials, no attempts."""
    import trendora.api.app as app_module

    monkeypatch.setattr(
        app_module,
        "_persist_research_report",
        lambda *args, **kwargs: None,
    )


def test_run_details_capture_actual_stage_and_request_without_content():
    envelope = {"usage": {"prompt_tokens": 40, "completion_tokens": 0, "total_tokens": 40}, "private": "never expose this"}
    request = {"model": "test", "messages": [{"role": "user", "content": "private source text"}]}
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=envelope))
    with collect_run_details() as details:
        with measure_stage("interpretation"):
            assert _post_chat_request(_config(), transport, request) == envelope
        result = details.as_dict("ai_interpretation")
    assert result["elapsed_ms"] >= 0
    assert result["stage_durations_ms"]["interpretation"] >= 0
    assert result["ai_requests"][0]["prompt_tokens"] == 40
    assert result["ai_requests"][0]["completion_tokens"] == 0
    assert result["ai_requests"][0]["stage"] == "interpretation"
    assert result["ai_requests"][0]["request_bytes"] > 0
    assert "private" not in json.dumps(result)
    assert "super-secret" not in json.dumps(result)


@pytest.mark.parametrize("usage", [None, "bad", {"prompt_tokens": True}, {"prompt_tokens": -1}, {"prompt_tokens": 2.5}, {"prompt_tokens": 2**54}])
def test_missing_or_invalid_usage_stays_unknown(usage):
    with collect_run_details() as details:
        _post_chat_request(_config(), httpx.MockTransport(lambda _: httpx.Response(200, json={"usage": usage})), {})
        item = details.as_dict("none")["ai_requests"][0]
    assert item["prompt_tokens"] is None
    assert item["completion_tokens"] is None


def test_nested_and_later_requests_do_not_inherit_details():
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    with collect_run_details() as outer:
        record_retry()
        with collect_run_details() as inner:
            _post_chat_request(_config(), transport, {})
        assert len(inner.as_dict("none")["ai_requests"]) == 1
        assert outer.as_dict("none")["ai_requests"] == []
        assert outer.as_dict("none")["retry_count"] == 1
    with collect_run_details() as later:
        assert later.as_dict("none")["retry_count"] == 0


def test_failed_request_counts_attempt_but_does_not_invent_usage():
    def fail(request):
        raise httpx.ConnectError("private provider message", request=request)
    with collect_run_details() as details:
        with pytest.raises(Exception):
            _post_chat_request(_config(), httpx.MockTransport(fail), {})
        result = details.as_dict("source_excerpts")
    assert len(result["ai_requests"]) == 1
    assert result["ai_requests"][0]["prompt_tokens"] is None
    assert "private" not in json.dumps(result)


def test_api_exposes_metadata_without_changing_the_six_field_snapshot():
    response = _app_with_report_service(_report_service([])).post(PATH, json=_payload())
    assert response.status_code == 200
    body = response.json()
    details = body["run_details"]
    assert details["elapsed_ms"] >= 0
    assert "collection" in details["stage_durations_ms"]
    assert "persistence" in details["stage_durations_ms"]
    assert details["finding_mode"] == "ai_interpretation"
    report = ResearchReportResponse(**body)
    before = snapshot_fingerprint(_snapshot_projection(report))
    report.run_details = None
    assert snapshot_fingerprint(_snapshot_projection(report)) == before
    assert len(_snapshot_projection(report)) == 6

