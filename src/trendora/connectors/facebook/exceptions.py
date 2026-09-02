"""Facebook connector errors. Messages and logs never include access tokens."""


class FacebookConnectorError(Exception):
    """Base error for the Facebook connector."""


class FacebookConfigurationError(FacebookConnectorError):
    """Invalid or missing Facebook client configuration or arguments."""


class FacebookHttpError(FacebookConnectorError):
    """Transport-level failure talking to the Graph API."""


class FacebookApiError(FacebookConnectorError):
    """Graph API returned a non-success status or an error envelope."""

    def __init__(self, message: str, *, status_code: int | None = None, reason: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason


class FacebookResponseError(FacebookConnectorError):
    """Response JSON was missing, malformed, or not an object."""