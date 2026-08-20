"""GitHub HTTP client tests. All responses are mocked; no network."""

from __future__ import annotations

import logging

import httpx
import pytest

from trendora.connectors.github.client import GitHubClient
from trendora.connectors.github.exceptions import (
    GitHubApiError,
    GitHubHttpError,
    GitHubResponseError,
)
from tests.fixtures.github_responses import (
    HTTP_NOT_FOUND,
    RATE_LIMIT_ERROR,
    REPO_A,
    REPO_A_FULL_NAME,
    REPO_B,
)

TEST_TOKEN = "ghp_test_token_not_real"


def _client(handler, *, token: str | None = None) -> GitHubClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return GitHubClient(token=token, http_client=http)


def test_get_repository_request_path_and_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host == "api.github.com"
        assert request.url.path == "/repos/octocat/hello-world"
        assert "/search" not in request.url.path
        assert "/commits" not in request.url.path
        assert "/issues" not in request.url.path
        assert "/pulls" not in request.url.path
        assert "Authorization" not in request.headers
        return httpx.Response(200, json=REPO_A)

    resource = _client(handler).get_repository("octocat", "hello-world")
    assert resource.full_name == REPO_A_FULL_NAME
    assert resource.stargazers_count == 100
    assert resource.topics == ["python", "machine-learning", "llm"]


def test_optional_fields_are_accepted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/example/ml-lib"
        return httpx.Response(200, json=REPO_B)

    resource = _client(handler).get_repository("example", "ml-lib")
    assert resource.description is None
    assert resource.language is None
    assert resource.license is None
    assert resource.stargazers_count == 0


def test_authorization_header_when_token_present() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TEST_TOKEN}"
        return httpx.Response(200, json=REPO_A)

    _client(handler, token=TEST_TOKEN).get_repository("octocat", "hello-world")


def test_http_error() -> None:
    with pytest.raises(GitHubHttpError, match="500"):
        _client(lambda request: httpx.Response(500, text="boom")).get_repository(
            "octocat", "hello-world"
        )


def test_not_found_api_error() -> None:
    with pytest.raises(GitHubApiError, match="Not Found"):
        _client(lambda request: httpx.Response(404, json=HTTP_NOT_FOUND)).get_repository(
            "octocat", "missing"
        )


def test_rate_limit_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json=RATE_LIMIT_ERROR,
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Limit": "60"},
        )

    with pytest.raises(GitHubApiError, match="rate limit") as exc_info:
        _client(handler).get_repository("octocat", "hello-world")
    assert exc_info.value.reason == "rate_limit"
    assert exc_info.value.status_code == 403


def test_malformed_json() -> None:
    with pytest.raises(GitHubResponseError, match="non-object JSON"):
        _client(lambda request: httpx.Response(200, text="not-json")).get_repository(
            "octocat", "hello-world"
        )


def test_malformed_payload() -> None:
    with pytest.raises(GitHubResponseError, match="non-object JSON"):
        _client(lambda request: httpx.Response(200, json=["not", "an", "object"])).get_repository(
            "octocat", "hello-world"
        )


def test_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failed", request=request)

    with pytest.raises(GitHubHttpError, match="HTTP request failed"):
        _client(handler).get_repository("octocat", "hello-world")


def test_token_is_never_written_to_logs(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TEST_TOKEN}"
        return httpx.Response(200, json=REPO_A)

    with caplog.at_level(logging.INFO, logger="trendora.connectors.github.client"):
        _client(handler, token=TEST_TOKEN).get_repository("octocat", "hello-world")
    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert TEST_TOKEN not in combined
    assert "Bearer" not in combined
    assert "Authorization" not in combined
