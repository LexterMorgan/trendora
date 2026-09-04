"""M23A research report API tests. Fully mocked, no live services."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from trendora.api import create_app
from trendora.api.app import (
    get_research_application_service,
    get_research_report_service,
)
from trendora.connectors.youtube.client import YouTubeClient
from trendora.research import (
    ResearchAIProviderError,
    ResearchAIProviderNotConfiguredError,
    ResearchAIResponseError,
    ResearchApplicationService,
    ResearchCapabilityResolver,
    ResearchInterpretationError,
    YouTubeResearchRetriever,
)
from tests.fixtures.youtube_responses import SEARCH_EMPTY, SEARCH_PAGE_1, VIDEOS_LIST_OK
from tests.unit.test_research_reporting import _query, _report_service

UTC = timezone.utc
FAKE_KEY = "super-secret-test-key"
PATH = "/api/v1/research/report"


def _payload() -> dict:
    payload = _query()
    payload["date_from"] = payload["date_from"].isoformat()
    payload["date_to"] = payload["date_to"].isoformat()
    return payload


def _youtube_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/search"):
        return httpx.Response(200, json=SEARCH_PAGE_1)
    return httpx.Response(200, json=VIDEOS_LIST_OK)


def _empty_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=SEARCH_EMPTY)


def _app_with_report_service(service) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_research_report_service] = lambda: service
    return TestClient(app)


def _research_app_service(handler) -> ResearchApplicationService:
    client = YouTubeClient("test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return ResearchApplicationService(
        ResearchCapabilityResolver(),
        {"youtube": YouTubeResearchRetriever(client)},
    )


class TestReportEndpoint:
    def test_completed_report_serialization(self) -> None:
        service = _report_service([])
        client = _app_with_report_service(service)
        response = client.post(PATH, json=_payload())
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert body["research"]["executed_sources"] == ["youtube"]
        assert body["evidence"] is not None
        assert body["interpretation"] is not None
        assert body["strategy"] is not None
        assert body["ideation"] is not None

    def test_completed_report_full_chain(self) -> None:
        service = _report_service([])
        body = _app_with_report_service(service).post(PATH, json=_payload()).json()
        assert body["ideation"]["content_briefs"][0]["idea_index"] == 0
        assert body["ideation"]["content_ideas"][0]["opportunity_indexes"] == [0]
        assert body["strategy"]["opportunities"][0]["gap_indexes"] == [0]
        assert body["strategy"]["content_gaps"][0]["supporting_interpretation_indexes"] == [0]
        assert body["interpretation"]["interpretations"][0]["citations"][0]["kind"] == "pattern"

    def test_no_evidence_serialization(self) -> None:
        service = _report_service([], handler=_empty_handler)
        body = _app_with_report_service(service).post(PATH, json=_payload()).json()
        assert body["status"] == "no_evidence"
        assert body["research"]["status"] == "completed"
        assert body["research"]["references"] == []
        assert body["evidence"] is None
        assert body["interpretation"] is None
        assert body["strategy"] is None
        assert body["ideation"] is None

    def test_trusted_provenance_at_every_stage(self) -> None:
        body = _app_with_report_service(_report_service([])).post(PATH, json=_payload()).json()
        for stage in ("interpretation", "strategy", "ideation"):
            assert body[stage]["model_provenance"] == {"provider": "test", "model": "test-model"}

    def test_missing_metric_null_vs_zero(self) -> None:
        body = _app_with_report_service(_report_service([])).post(PATH, json=_payload()).json()
        # reference 0 (VIDEO_1): view=100, like=10, comment=2
        metrics = body["research"]["references"][0]["metrics"]
        assert metrics["view_count"] == 100
        assert metrics["like_count"] == 10
        # reference 1 (VIDEO_2): view=5 only -> like/comment null
        metrics = body["research"]["references"][1]["metrics"]
        assert metrics["view_count"] == 5
        assert metrics["like_count"] is None
        assert metrics["comment_count"] is None
        facts = {f["field"]: f["value"] for f in body["evidence"]["analyses"][1]["facts"]}
        assert facts["like_count"] is None
        assert facts["view_count"] == 5

    def test_pattern_provenance_ids_preserved(self) -> None:
        body = _app_with_report_service(_report_service([])).post(PATH, json=_payload()).json()
        patterns = body["evidence"]["patterns"]
        assert patterns
        for pattern in patterns:
            assert pattern["analyzed_count"] == pattern["matching_count"] + pattern["non_matching_count"]
            assert len(pattern["matching_reference_ids"]) == pattern["matching_count"]
            assert len(pattern["non_matching_reference_ids"]) == pattern["non_matching_count"]
            assert all(rid["source_code"] == "youtube" for rid in pattern["matching_reference_ids"])

    def test_request_rejects_extra_fields(self) -> None:
        payload = _payload()
        payload["provider"] = "client-controlled"
        response = _app_with_report_service(_report_service([])).post(PATH, json=payload)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"


class TestFacebookReportEndpoint:
    def _payload(self) -> dict:
        return {
            "topic": "AI education",
            "market": "SG",
            "date_from": "2026-08-01",
            "date_to": "2026-08-31",
            "sources": ["facebook"],
            "result_limit": 10,
            "facebook_page_id": "page1",
        }

    def test_facebook_page_id_forwarded_through_report_pipeline(self) -> None:
        from tests.unit.test_research_facebookresearch import (
            RecordingFacebookClient,
            _fb_post,
            _report_service as _facebook_report_service,
        )

        client = RecordingFacebookClient([_fb_post("p1"), _fb_post("p2")])
        service = _facebook_report_service(client, [])
        body = _app_with_report_service(service).post(PATH, json=self._payload())
        assert body.status_code == 200
        payload = body.json()
        assert payload["status"] == "completed"
        assert payload["research"]["executed_sources"] == ["facebook"]
        assert payload["research"]["query"]["facebook_page_id"] == "page1"
        assert [r["content_external_id"] for r in payload["research"]["references"]] == ["p1", "p2"]
        assert client.calls[0]["page_id"] == "page1"

    def test_facebook_zero_posts_report_no_evidence(self) -> None:
        from tests.unit.test_research_facebookresearch import (
            RecordingFacebookClient,
            _report_service as _facebook_report_service,
        )

        service = _facebook_report_service(RecordingFacebookClient([]), [])
        body = _app_with_report_service(service).post(PATH, json=self._payload())
        assert body.status_code == 200
        payload = body.json()
        assert payload["status"] == "no_evidence"
        assert payload["research"]["references"] == []

    def test_facebook_missing_page_id_returns_422(self) -> None:
        payload = self._payload()
        del payload["facebook_page_id"]
        response = _app_with_report_service(_report_service([])).post(PATH, json=payload)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_research_request"


class TestReportErrors:
    def _post(self, service) -> dict:
        return _app_with_report_service(service).post(PATH, json=_payload())

    def test_not_configured_maps_503(self) -> None:
        class Failing:
            def build_report(self, **kwargs):
                raise ResearchAIProviderNotConfiguredError("missing")

        body = self._post(Failing())
        assert body.status_code == 503
        assert body.json()["error"]["code"] == "ai_provider_not_configured"

    def test_provider_failure_maps_502(self) -> None:
        class Failing:
            def build_report(self, **kwargs):
                raise ResearchAIProviderError("upstream")

        body = self._post(Failing())
        assert body.status_code == 502
        assert body.json()["error"]["code"] == "ai_provider_error"

    def test_response_invalid_maps_502(self) -> None:
        class Failing:
            def build_report(self, **kwargs):
                raise ResearchAIResponseError("bad json")

        body = self._post(Failing())
        assert body.status_code == 502
        assert body.json()["error"]["code"] == "ai_response_invalid"

    def test_grounding_failure_maps_502(self) -> None:
        class Failing:
            def build_report(self, **kwargs):
                raise ResearchInterpretationError("ungrounded")

        body = self._post(Failing())
        assert body.status_code == 502
        assert body.json()["error"]["code"] == "ai_response_invalid"

    def test_errors_do_not_leak_secrets_or_detail(self) -> None:
        class Failing:
            def build_report(self, **kwargs):
                raise ResearchAIProviderError("secret: super-secret-test-key endpoint x")

        body = self._post(Failing()).json()
        raw = str(body)
        assert FAKE_KEY not in raw
        assert "Traceback" not in raw
        # fixed public message, not the exception message
        assert body["error"]["message"] == "AI provider failed."


class TestExistingResearchEndpoint:
    def test_research_endpoint_unchanged(self) -> None:
        app = create_app()
        app.dependency_overrides[get_research_application_service] = lambda: _research_app_service(
            _youtube_handler
        )
        client = TestClient(app)
        payload = _query()
        payload["date_from"] = "2026-08-01"
        payload["date_to"] = "2026-08-31"
        response = client.post("/api/v1/research", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

    def test_openapi_has_all_routes(self) -> None:
        app = create_app()
        paths = app.openapi()["paths"]
        assert "post" in paths[PATH]
        assert "post" in paths["/api/v1/research"]
        assert "get" in paths["/api/v1/forecasts/github/{content_item_id}"]


class TestRuntimeClients:
    def test_owned_clients_close_once(self, monkeypatch) -> None:
        import trendora.api.app as app_module

        closed = {"youtube": 0, "http": 0}

        class FakeYT:
            def close(self):
                closed["youtube"] += 1

        class FakeHTTP:
            def __init__(self, timeout=None):
                pass

            def close(self):
                closed["http"] += 1

        class FakeSettings:
            ai_provider = "p"
            ai_model = "m"
            ai_endpoint_url = "https://provider.test/v1/chat/completions"
            ai_api_key = FAKE_KEY
            youtube_api_key = "yt-key"
            meta_access_token = None
            meta_graph_api_version = None

        monkeypatch.setattr(app_module, "get_settings", lambda: FakeSettings())
        monkeypatch.setattr(app_module, "YouTubeClient", lambda key: FakeYT())
        monkeypatch.setattr(app_module.httpx, "Client", FakeHTTP)

        generator = app_module.get_research_report_service()
        service = next(generator)
        assert service is not None
        generator.close()
        assert closed == {"youtube": 1, "http": 1}

    def test_later_client_construction_failure_closes_earlier_clients_once(
        self, monkeypatch
    ) -> None:
        import trendora.api.app as app_module

        closed = {"youtube": 0, "http": 0}

        class FakeYT:
            def close(self):
                closed["youtube"] += 1

        class FakeHTTP:
            def __init__(self, timeout=None):
                pass

            def close(self):
                closed["http"] += 1

        class FailingFacebook:
            def __init__(self, token, version):
                raise RuntimeError("facebook construction failed")

        class FakeSettings:
            ai_provider = "p"
            ai_model = "m"
            ai_endpoint_url = "https://provider.test/v1/chat/completions"
            ai_api_key = FAKE_KEY
            youtube_api_key = "yt-key"
            meta_access_token = "tok"
            meta_graph_api_version = "v19.0"

        monkeypatch.setattr(app_module, "get_settings", lambda: FakeSettings())
        monkeypatch.setattr(app_module, "YouTubeClient", lambda key: FakeYT())
        monkeypatch.setattr(app_module, "FacebookPublicClient", FailingFacebook)
        monkeypatch.setattr(app_module.httpx, "Client", FakeHTTP)

        generator = app_module.get_research_report_service()
        with pytest.raises(RuntimeError, match="facebook construction failed"):
            next(generator)
        # http was never created; the already-created youtube client closed once.
        assert closed == {"youtube": 1, "http": 0}

    def test_service_build_failure_closes_all_created_clients_once(
        self, monkeypatch
    ) -> None:
        import trendora.api.app as app_module

        closed = {"youtube": 0, "http": 0}

        class FakeYT:
            def close(self):
                closed["youtube"] += 1

        class FakeHTTP:
            def __init__(self, timeout=None):
                pass

            def close(self):
                closed["http"] += 1

        class FakeSettings:
            ai_provider = "p"
            ai_model = "m"
            ai_endpoint_url = "https://provider.test/v1/chat/completions"
            ai_api_key = FAKE_KEY
            youtube_api_key = "yt-key"
            meta_access_token = None
            meta_graph_api_version = None

        def fail_build(**kwargs):
            raise RuntimeError("service build failed")

        monkeypatch.setattr(app_module, "get_settings", lambda: FakeSettings())
        monkeypatch.setattr(app_module, "YouTubeClient", lambda key: FakeYT())
        monkeypatch.setattr(app_module.httpx, "Client", FakeHTTP)
        monkeypatch.setattr(app_module, "build_research_report_service", fail_build)

        generator = app_module.get_research_report_service()
        with pytest.raises(RuntimeError, match="service build failed"):
            next(generator)
        assert closed == {"youtube": 1, "http": 1}

    def test_report_dependency_teardown_closes_facebook_exactly_once(
        self, monkeypatch
    ) -> None:
        import trendora.api.app as app_module

        closed = {"facebook": 0}

        class FakeFB:
            def close(self):
                closed["facebook"] += 1

        class FakeSettings:
            ai_provider = "p"
            ai_model = "m"
            ai_endpoint_url = "https://provider.test/v1/chat/completions"
            ai_api_key = FAKE_KEY
            youtube_api_key = None
            meta_access_token = "tok"
            meta_graph_api_version = "v19.0"

        monkeypatch.setattr(app_module, "get_settings", lambda: FakeSettings())
        monkeypatch.setattr(app_module, "FacebookPublicClient", lambda t, v: FakeFB())
        monkeypatch.setattr(app_module.httpx, "Client", lambda **_: type("C", (), {"close": lambda self: None})())

        generator = app_module.get_research_report_service()
        assert next(generator) is not None
        generator.close()
        assert closed == {"facebook": 1}

    def test_report_service_build_failure_closes_created_facebook_client(
        self, monkeypatch
    ) -> None:
        import trendora.api.app as app_module

        closed = {"youtube": 0, "facebook": 0, "http": 0}

        class FakeYT:
            def close(self):
                closed["youtube"] += 1

        class FakeFB:
            def close(self):
                closed["facebook"] += 1

        class FakeHTTP:
            def __init__(self, timeout=None):
                pass

            def close(self):
                closed["http"] += 1

        class FakeSettings:
            ai_provider = "p"
            ai_model = "m"
            ai_endpoint_url = "https://provider.test/v1/chat/completions"
            ai_api_key = FAKE_KEY
            youtube_api_key = "yt-key"
            meta_access_token = "tok"
            meta_graph_api_version = "v19.0"

        def fail_build(**kwargs):
            raise RuntimeError("service build failed")

        monkeypatch.setattr(app_module, "get_settings", lambda: FakeSettings())
        monkeypatch.setattr(app_module, "YouTubeClient", lambda key: FakeYT())
        monkeypatch.setattr(app_module, "FacebookPublicClient", lambda t, v: FakeFB())
        monkeypatch.setattr(app_module.httpx, "Client", FakeHTTP)
        monkeypatch.setattr(app_module, "build_research_report_service", fail_build)

        generator = app_module.get_research_report_service()
        with pytest.raises(RuntimeError, match="service build failed"):
            next(generator)
        assert closed == {"youtube": 1, "facebook": 1, "http": 1}

    def test_application_dependency_teardown_closes_facebook_exactly_once(
        self, monkeypatch
    ) -> None:
        import trendora.api.app as app_module

        closed = {"youtube": 0, "facebook": 0}

        class FakeYT:
            def close(self):
                closed["youtube"] += 1

        class FakeFB:
            def close(self):
                closed["facebook"] += 1

        class FakeSettings:
            youtube_api_key = "yt-key"
            meta_access_token = "tok"
            meta_graph_api_version = "v19.0"

        monkeypatch.setattr(app_module, "get_settings", lambda: FakeSettings())
        monkeypatch.setattr(app_module, "YouTubeClient", lambda key: FakeYT())
        monkeypatch.setattr(app_module, "FacebookPublicClient", lambda t, v: FakeFB())

        generator = app_module.get_research_application_service()
        assert next(generator) is not None
        generator.close()
        assert closed == {"youtube": 1, "facebook": 1}
