"""Public-web discovery route: configured gateway only, bounded output."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.support.app import create_test_app
from trendora.api.app import get_discover_gateway
from trendora.connectors.web_search import SearchResult

PATH = "/api/v1/discover"


class FakeGateway:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []
        self.closed = False

    def search(self, query: str, *, limit: int = 15) -> list[SearchResult]:
        self.calls.append((query, limit))
        return self.results

    def close(self) -> None:
        self.closed = True


def _client(gateway) -> TestClient:
    app = create_test_app()
    app.dependency_overrides[get_discover_gateway] = lambda: gateway
    return TestClient(app)


def test_returns_configured_gateway_results_in_order_with_bounded_text() -> None:
    gateway = FakeGateway(
        [
            SearchResult(
                url="https://example.test/first",
                title="t" * 250,
                snippet="d" * 300,
                domain="example.test",
            ),
            SearchResult(
                url="https://example.test/second",
                title="Second",
                snippet="Short description",
                domain="example.test",
            ),
        ]
    )
    client = _client(gateway)

    response = client.get(PATH, params={"q": "  climate  ", "limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "climate"
    assert body["status"] == "ok"
    assert [source["url"] for source in body["sources"]] == [
        "https://example.test/first",
        "https://example.test/second",
    ]
    assert gateway.calls == [("climate", 2)]
    first = body["sources"][0]
    assert first["source_code"] == "public_web"
    assert first["content_external_id"] == "https://example.test/first"
    assert first["published_at"] is None
    assert len(first["title"]) == 200
    assert len(first["description"]) == 280
    assert body["sources"][1]["title"] == "Second"


def test_blank_or_overlong_query_is_rejected_without_searching() -> None:
    gateway = FakeGateway([])
    client = _client(gateway)

    blank = client.get(PATH, params={"q": "   "})
    overlong = client.get(PATH, params={"q": "x" * 201})

    assert blank.status_code == 400
    assert overlong.status_code == 400
    assert gateway.calls == []


def test_unconfigured_gateway_is_unavailable() -> None:
    response = _client(None).get(PATH, params={"q": "climate"})

    assert response.status_code == 503
