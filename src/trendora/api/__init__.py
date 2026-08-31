"""Trendora HTTP API layer (M11B).

Thin FastAPI adapter over the M10 V1 GitHub forecast product. Exposes exactly
one read endpoint; all forecast behavior lives in ``trendora.product`` (M10).
No SQL, no connectors, no persistence, no auth, no rate limiting.
"""

from trendora.api.app import create_app, get_github_forecast_product
from trendora.api.models import ForecastPointResponse, ForecastResponse

__all__ = [
    "ForecastPointResponse",
    "ForecastResponse",
    "create_app",
    "get_github_forecast_product",
]
