"""Facebook Graph API connector (M25A).

Isolated client for public Facebook Page posts and visible engagement. No
OAuth/token persistence, no keyword search, no dashboard/API integration yet.
"""

from trendora.connectors.facebook.client import FacebookPublicClient
from trendora.connectors.facebook.exceptions import (
    FacebookApiError,
    FacebookConfigurationError,
    FacebookConnectorError,
    FacebookHttpError,
    FacebookResponseError,
)
from trendora.connectors.facebook.schemas import FacebookPostResource

__all__ = [
    "FacebookApiError",
    "FacebookConfigurationError",
    "FacebookConnectorError",
    "FacebookHttpError",
    "FacebookPostResource",
    "FacebookPublicClient",
    "FacebookResponseError",
]