"""Stack Exchange connector errors."""


class StackExchangeConnectorError(Exception):
    """Base error for the Stack Exchange connector."""


class StackExchangeConfigurationError(StackExchangeConnectorError):
    """Missing or invalid Stack Exchange configuration."""


class StackExchangeHttpError(StackExchangeConnectorError):
    """Transport-level or HTTP failure talking to the Stack Exchange API."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class StackExchangeApiError(StackExchangeConnectorError):
    """Stack Exchange wrapper reported an API error."""

    def __init__(
        self,
        message: str,
        *,
        error_id: int | None = None,
        error_name: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_id = error_id
        self.error_name = error_name
        self.status_code = status_code


class StackExchangeResponseError(StackExchangeConnectorError):
    """Response JSON was missing, malformed, or the wrong shape."""


class StackExchangeItemError(StackExchangeConnectorError):
    """One question could not be ingested; other questions may continue."""
