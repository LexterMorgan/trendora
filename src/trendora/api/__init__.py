"""Trendora HTTP API layer (M11B forecast, M15 research).

Thin FastAPI adapters. The forecast endpoint exposes the M10 GitHub forecast
product; the research endpoint exposes the M15 research application service.
No SQL, no connectors, no persistence, no auth, no rate limiting in the
adapter layer.
"""

from trendora.api.app import (
    create_app,
    get_github_forecast_product,
    get_research_application_service,
)
from trendora.api.models import ForecastPointResponse, ForecastResponse
from trendora.api.research_models import (
    ResearchCoverageResponse,
    ResearchMetricsResponse,
    ResearchQueryResponse,
    ResearchReferenceResponse,
    ResearchRequest,
    ResearchResponse,
    SourceCoverageResponse,
)

__all__ = [
    "ForecastPointResponse",
    "ForecastResponse",
    "ResearchCoverageResponse",
    "ResearchMetricsResponse",
    "ResearchQueryResponse",
    "ResearchReferenceResponse",
    "ResearchRequest",
    "ResearchResponse",
    "SourceCoverageResponse",
    "create_app",
    "get_github_forecast_product",
    "get_research_application_service",
]
