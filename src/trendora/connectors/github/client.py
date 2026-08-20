"""GitHub REST API HTTP client. No SQLAlchemy. No normalization."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import ValidationError

from trendora.connectors.github.exceptions import (
    GitHubApiError,
    GitHubConnectorError,
    GitHubHttpError,
    GitHubResponseError,
)
from trendora.connectors.github.schemas import RepositoryResource

logger = logging.getLogger("trendora.connectors.github.client")

GITHUB_API_BASE = "https://api.github.com"
_USER_AGENT = "Trendora/0.0.1"
_ACCEPT = "application/vnd.github+json"
_API_VERSION = "2022-11-28"


class GitHubClient:
    """HTTPS client for official GitHub REST repository reads.

    Search, commits, issues, pull requests, and GraphQL are not implemented.
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        key = (token or "").strip()
        self._token = key or None
        self._owns_http = http_client is None
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": _ACCEPT,
            "X-GitHub-Api-Version": _API_VERSION,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(20.0, connect=10.0),
            headers=headers,
        )
        if http_client is not None and self._token:
            self._http.headers["Authorization"] = f"Bearer {self._token}"
            self._http.headers["Accept"] = _ACCEPT
            self._http.headers["X-GitHub-Api-Version"] = _API_VERSION
            self._http.headers.setdefault("User-Agent", _USER_AGENT)

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get_repository(self, owner: str, repo: str) -> RepositoryResource:
        endpoint = f"repos/{owner}/{repo}"
        logger.info("github.api.request owner=%s repo=%s", owner, repo)
        try:
            response = self._http.get(f"{GITHUB_API_BASE}/{endpoint}")
        except httpx.HTTPError as exc:
            logger.exception(
                "github.api.http_failure owner=%s repo=%s error_type=%s",
                owner,
                repo,
                type(exc).__name__,
            )
            raise GitHubHttpError(
                f"GitHub HTTP request failed for /repos/{owner}/{repo}"
            ) from exc

        try:
            decoded = response.json()
        except ValueError:
            decoded = None

        if response.status_code >= 400:
            raise _error_from_response(owner, repo, response, decoded)

        if not isinstance(decoded, dict):
            raise GitHubResponseError(
                f"GitHub /repos/{owner}/{repo} returned non-object JSON"
            )
        try:
            return RepositoryResource.model_validate(decoded)
        except ValidationError as exc:
            raise GitHubResponseError(
                f"GitHub /repos/{owner}/{repo} payload was malformed"
            ) from exc


def _error_from_response(
    owner: str,
    repo: str,
    response: httpx.Response,
    decoded: object,
) -> GitHubConnectorError:
    status = response.status_code
    remaining = response.headers.get("X-RateLimit-Remaining")
    limit = response.headers.get("X-RateLimit-Limit")
    if remaining is not None or limit is not None:
        logger.info("github.api.rate_limit remaining=%s limit=%s", remaining, limit)

    message = "GitHub API error"
    if isinstance(decoded, dict) and isinstance(decoded.get("message"), str):
        text = decoded["message"].strip()
        if text:
            message = text

    rate_limited = status in {403, 429} and (
        remaining == "0" or "rate limit" in message.lower()
    )
    if rate_limited:
        logger.error(
            "github.api.rate_limited owner=%s repo=%s status=%s",
            owner,
            repo,
            status,
        )
        return GitHubApiError(
            f"GitHub rate limit exceeded for /repos/{owner}/{repo}: {message}",
            status_code=status,
            reason="rate_limit",
        )

    if isinstance(decoded, dict) and decoded.get("message"):
        logger.error(
            "github.api.error owner=%s repo=%s status=%s",
            owner,
            repo,
            status,
        )
        return GitHubApiError(
            f"GitHub /repos/{owner}/{repo} error: {message}",
            status_code=status,
        )

    logger.error(
        "github.api.http_error owner=%s repo=%s status=%s",
        owner,
        repo,
        status,
    )
    return GitHubHttpError(
        f"GitHub /repos/{owner}/{repo} failed with HTTP {status}",
        status_code=status,
    )

