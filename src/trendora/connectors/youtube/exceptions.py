"""YouTube connector errors. Messages must never include API keys."""


class YouTubeConnectorError(Exception):
    """Base error for the YouTube connector."""


class YouTubeConfigurationError(YouTubeConnectorError):
    """Missing or invalid YouTube configuration."""


class EmptyWatchlistError(YouTubeConfigurationError):
    """Ingestion was requested with no channel IDs."""


class InvalidYouTubeWatchlistError(YouTubeConfigurationError):
    """Watchlist string contains an invalid channel identity."""


class YouTubeHttpError(YouTubeConnectorError):
    """Transport-level failure talking to the YouTube API."""


class YouTubeApiError(YouTubeConnectorError):
    """YouTube returned an API error payload (quota, forbidden, etc.)."""

    def __init__(self, message: str, *, status_code: int | None = None, reason: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason


class YouTubeResponseError(YouTubeConnectorError):
    """Response JSON was missing, malformed, or not an object."""


class ChannelIngestionError(YouTubeConnectorError):
    """One channel could not be ingested; other watchlist entries may continue."""
