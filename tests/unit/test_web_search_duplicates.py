from datetime import date, datetime, timezone

import httpx
import pytest

from trendora.connectors.web_search.searxng_gateway import SearxngGateway
from trendora.connectors.web_search.serper_gateway import SerperGateway
from trendora.connectors.web_search.url_safety import result_identity
from trendora.research.models import ResearchQuery
from trendora.research.web_search import WebSearchResearchRetriever


@pytest.mark.parametrize("parameter", [
    "utm_id", "utm_source", "utm_medium", "utm_campaign", "utm_term",
    "utm_content", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
])
def test_only_campaign_parameter_is_removed_from_comparison(parameter):
    url = f"https://example.test/story?{parameter}=x&id=7&tag=a%2Fb&tag=c+d#section"
    assert result_identity(url) == "https://example.test/story?id=7&tag=a%2Fb&tag=c+d#section"


def test_encoded_campaign_key_and_empty_campaign_value():
    assert result_identity("https://example.test/?%75tm_source=x&utm_content=") == "https://example.test/"


@pytest.mark.parametrize("backend", ["searxng", "serper"])
def test_campaign_duplicates_do_not_use_result_slots_or_rewrite_citations(backend):
    original = "https://example.test/story?id=7&utm_source=newsletter"
    urls = [
        original,
        "https://example.test/story?utm_campaign=spring&id=7",
        "https://example.test/story?id=7",
        "https://example.test/another-story",
    ]
    calls = []

    def respond(request):
        calls.append(request)
        url_field, text_field, root = (
            ("url", "content", "results") if backend == "searxng"
            else ("link", "snippet", "organic")
        )
        return httpx.Response(200, json={root: [
            {url_field: url, "title": f"Source {i}", text_field: f"Excerpt {i}"}
            for i, url in enumerate(urls)
        ]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        gateway = (
            SearxngGateway("http://localhost:8888", http_client=client)
            if backend == "searxng" else SerperGateway("fictional-key", http_client=client)
        )
        retriever = WebSearchResearchRetriever(gateway)
        query = ResearchQuery(
            topic="fictional topic", markets=(),
            date_from=date(2026, 10, 1), date_to=date(2026, 10, 11),
            source_codes=("public_web",), result_limit=2,
        )
        refs = retriever.normalize(retriever.collect(
            query, collected_at=datetime(2026, 10, 11, tzinfo=timezone.utc),
        ))

    assert len(calls) == (7 if backend == "searxng" else 1)
    assert [ref.url for ref in refs] == [original, urls[-1]]
    assert [ref.content_external_id for ref in refs] == [original, urls[-1]]
    assert refs[0].title == "Source 0" and refs[0].description == "Excerpt 0"
    assert all(ref.published_at is None for ref in refs)


@pytest.mark.parametrize("backend", ["searxng", "serper"])
def test_distinct_pages_and_identical_snippets_are_not_merged(backend):
    urls = [
        "https://example.test/story?id=1",
        "https://example.test/story?id=2",
        "https://example.test/story?page=2",
        "https://example.test/story?ref=different",
        "https://example.test/story#/different-route",
        "https://other.test/story?id=1",
        "http://example.test/story?id=1",
        "https://example.test/Story?id=1",
        "https://example.test/story?utm_custom=content",
        "https://example.test/story?tag=a&tag=b",
        "https://example.test/story?tag=b&tag=a",
        "https://example.test/story?filter=",
        "https://example.test/story",
    ]

    def respond(request):
        url_field, text_field, root = (
            ("url", "content", "results") if backend == "searxng"
            else ("link", "snippet", "organic")
        )
        return httpx.Response(200, json={root: [
            {url_field: url, "title": "Same title", text_field: "Same short snippet"}
            for url in urls
        ]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        gateway = (
            SearxngGateway("http://localhost:8888", http_client=client)
            if backend == "searxng" else SerperGateway("fictional-key", http_client=client)
        )
        assert [item.url for item in gateway.search("topic", limit=15)] == urls
