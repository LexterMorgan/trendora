"""Trendora product layer over M5 analytics, M6 forecasting, and M7 diagnostics.

M10 implements the V1 GitHub repository forecast slice. This package is the
boundary between in-memory forecasting/diagnostics and future API/dashboard
layers. It contains no SQL, no connectors, no persistence, and no schema.
"""

from trendora.product.github_forecast import (
    V1_HORIZON,
    V1_INTERVAL,
    V1_METRICS,
    V1_MIN_OBSERVATIONS,
    V1_ORIGIN,
    V1_SOURCE,
    GitHubForecastProduct,
    GitHubForecastRequest,
    GitHubForecastResult,
)

__all__ = [
    "V1_HORIZON",
    "V1_INTERVAL",
    "V1_METRICS",
    "V1_MIN_OBSERVATIONS",
    "V1_ORIGIN",
    "V1_SOURCE",
    "GitHubForecastProduct",
    "GitHubForecastRequest",
    "GitHubForecastResult",
]
