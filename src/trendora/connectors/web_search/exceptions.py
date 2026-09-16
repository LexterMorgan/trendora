"""Web search connector errors. Messages must never include the API key."""


class WebSearchConnectorError(Exception):
    """Base error for the web search connector."""


class WebSearchConfigurationError(WebSearchConnectorError):
    """Missing or invalid web search configuration."""


class WebSearchHttpError(WebSearchConnectorError):
    """Transport-level failure talking to the search provider."""


class WebSearchApiError(WebSearchConnectorError):
    """The provider returned a non-success status or malformed payload."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class WebSearchResponseError(WebSearchConnectorError):
    """Response JSON was missing, malformed, or not an object."""
