"""GitHub REST repository connector."""

from trendora.connectors.github.connector import GitHubConnector, build_github_connector
from trendora.connectors.github.exceptions import GitHubConfigurationError, GitHubConnectorError

__all__ = [
    "GitHubConfigurationError",
    "GitHubConnector",
    "GitHubConnectorError",
    "build_github_connector",
]
