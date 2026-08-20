"""GitHub connector errors."""


class GitHubConnectorError(Exception):
    """Base error for the GitHub connector."""


class GitHubConfigurationError(GitHubConnectorError):
    """Missing or invalid GitHub configuration."""


class GitHubHttpError(GitHubConnectorError):
    """Transport-level or HTTP failure talking to the GitHub API."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GitHubApiError(GitHubConnectorError):
    """GitHub returned an API error payload."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason


class GitHubResponseError(GitHubConnectorError):
    """Response JSON was missing, malformed, or the wrong shape."""


class GitHubItemError(GitHubConnectorError):
    """One repository could not be ingested; other repositories may continue."""
