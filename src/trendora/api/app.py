"""FastAPI application exposing the M10 GitHub forecast product (M11B).

HTTP
  → this route
  → M10 ``GitHubForecastProduct``
  → M5 / M6A / M7
  → response

Exactly one read endpoint. The API is a thin adapter: it validates the request,
calls the M10 product, and serializes the result. No forecasting logic, no
SQL, no connectors, no persistence, no auth, no rate limiting.
"""

from __future__ import annotations

from collections.abc import Generator
from uuid import UUID

from fastapi import Depends, FastAPI, Query

from trendora.analytics.service import AnalyticsService
from trendora.db.session import get_session_factory
from trendora.forecasting.exceptions import ForecastingValidationError
from trendora.product import V1_METRICS, GitHubForecastProduct, GitHubForecastRequest

from trendora.api.errors import register_error_handlers
from trendora.api.models import ForecastResponse, to_forecast_response


def get_github_forecast_product() -> Generator[GitHubForecastProduct, None, None]:
    """FastAPI dependency: M10 product over the established M5 read path.

    Opens the application database session and builds ``AnalyticsService``
    exactly the way the rest of the repository does (``from_session``). No
    SQL is written here; M10 queries M5. Tests override this dependency.
    """

    session = get_session_factory()()
    try:
        yield GitHubForecastProduct(AnalyticsService.from_session(session))
    finally:
        session.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Trendora API",
        description=(
            "Trendora read-model API. V1 exposes the GitHub forecast product "
            "(M10): naive level forecasts of repository stargazer_count / "
            "fork_count, 4 points at a 7-day generation interval."
        ),
    )
    register_error_handlers(app)

    @app.get(
        "/api/v1/forecasts/github/{content_item_id}",
        response_model=ForecastResponse,
        summary="GitHub repository forecast",
        description=(
            "Trendora-derived naive level forecast for a GitHub repository "
            "content_item (stargazer_count or fork_count). Exactly 4 points "
            "at a 7-day generation interval, minimum 4 stored observations, "
            "origin=trendora_forecast. Forecast timestamps are "
            "Trendora-generated (latest observed_at + n*7 days); they are not "
            "source observation timestamps."
        ),
    )
    def github_forecast(
        content_item_id: UUID,
        metric: str | None = Query(
            default=None,
            description="Forecast metric. One of: stargazer_count, fork_count.",
        ),
        product: GitHubForecastProduct = Depends(get_github_forecast_product),
    ) -> ForecastResponse:
        if metric not in V1_METRICS:
            raise ForecastingValidationError(
                f"metric must be one of {sorted(V1_METRICS)}; got {metric!r}"
            )
        result = product.forecast(
            GitHubForecastRequest(content_item_id=content_item_id, metric_name=metric)
        )
        return to_forecast_response(result)

    return app
