"""Hacker News connector errors."""


class HackerNewsConnectorError(Exception):
    """Base error for the Hacker News connector."""


class HackerNewsConfigurationError(HackerNewsConnectorError):
    """Missing or invalid Hacker News configuration."""


class HackerNewsHttpError(HackerNewsConnectorError):
    """Transport-level or HTTP failure talking to the Hacker News API."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class HackerNewsResponseError(HackerNewsConnectorError):
    """Response JSON was missing, malformed, or the wrong shape."""


class HackerNewsItemError(HackerNewsConnectorError):
    """One item could not be ingested; other items may continue."""
