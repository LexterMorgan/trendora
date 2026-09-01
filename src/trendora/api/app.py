"""FastAPI application exposing the M10 GitHub forecast product and M15 research.

Forecast:
  HTTP → this route → M10 GitHubForecastProduct → M5 / M6A / M7 → response

Research:
  HTTP → this route → research application service → ResearchQuery →
  capability resolution → YouTube retriever → ResearchRun → response

Thin adapters only: no forecasting/retrieval logic, no SQL, no connectors in
the route layer, no persistence, no auth, no rate limiting.
"""

from __future__ import annotations

from collections.abc import Generator
from uuid import UUID

from fastapi import Depends, FastAPI, Query

from trendora.analytics.service import AnalyticsService
from trendora.config import get_settings
from trendora.connectors.youtube.client import YouTubeClient
from trendora.db.session import get_session_factory
from trendora.forecasting.exceptions import ForecastingValidationError
from trendora.product import V1_METRICS, GitHubForecastProduct, GitHubForecastRequest
from trendora.research.application import ResearchApplicationService, build_research_application_service
from trendora.research.exceptions import ResearchNoCoverageError
from trendora.research.models import ResearchRunStatus

from trendora.api.errors import register_error_handlers
from trendora.api.models import ForecastResponse, to_forecast_response
from trendora.api.research_models import (
    ResearchRequest,
    ResearchResponse,
    to_research_response,
)


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


def get_research_application_service() -> Generator[ResearchApplicationService, None, None]:
    """FastAPI dependency: synchronous research application service.

    Builds a YouTube client only when ``YOUTUBE_API_KEY`` is configured. If the
    key is missing, no runtime retriever is registered; an available YouTube
    capability then surfaces as a ``research_source_not_configured`` error.
    Tests override this dependency.
    """

    api_key = get_settings().youtube_api_key
    client = YouTubeClient(api_key) if api_key else None
    service = build_research_application_service(youtube_client=client)
    try:
        yield service
    finally:
        if client is not None:
            client.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Trendora API",
        description=(
            "Trendora read-model API. V1 exposes the GitHub forecast product "
            "(M10) and the YouTube-first research workflow (M15): query + "
            "capability coverage + normalized in-memory references."
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

    @app.post(
        "/api/v1/research",
        response_model=ResearchResponse,
        summary="Run YouTube-first research",
        description=(
            "Run one synchronous research request: topic + market + date "
            "window → capability coverage → YouTube public discovery and "
            "enrichment → normalized in-memory references. Returns the "
            "ResearchRun state (query, coverage, execution status, "
            "references). No persistence, no AI, no derived metrics."
        ),
        responses={
            422: {"description": "Invalid research request, or no requested source has usable coverage"},
            503: {"description": "Source is available but no runtime retriever is configured"},
            502: {"description": "Upstream YouTube failure"},
        },
    )
    def research(
        payload: ResearchRequest,
        service: ResearchApplicationService = Depends(get_research_application_service),
    ) -> ResearchResponse:
        run = service.execute(
            topic=payload.topic,
            market=payload.market,
            date_from=payload.date_from,
            date_to=payload.date_to,
            sources=payload.sources,
            result_limit=payload.result_limit,
        )
        if run.status is ResearchRunStatus.BLOCKED:
            raise ResearchNoCoverageError(
                "no requested source can satisfy the required capability"
            )
        return to_research_response(run)

    return app
