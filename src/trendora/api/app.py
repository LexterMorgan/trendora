"""FastAPI application exposing the M10 GitHub forecast product and research.

Forecast:
  HTTP → this route → M10 GitHubForecastProduct → M5 / M6A / M7 → response

Research:
  HTTP → this route → research application service → ResearchQuery →
  capability resolution → configured source retriever → ResearchRun → response

Thin adapters only: no forecasting/retrieval logic, no SQL, no connectors in
the route layer, no persistence, no auth, no rate limiting.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import ExitStack
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from trendora.analytics.service import AnalyticsService
from trendora.config import get_settings
from trendora.connectors.facebook.client import FacebookPublicClient
from trendora.connectors.youtube.client import YouTubeClient
from trendora.db.session import get_session_factory
from trendora.forecasting.exceptions import ForecastingValidationError
from trendora.models.research import ResearchReportRecord
from trendora.product import V1_METRICS, GitHubForecastProduct, GitHubForecastRequest
from trendora.research.ai_provider import build_ai_provider_config
from trendora.research.adapter import adapt_research_request
from trendora.research.application import ResearchApplicationService, build_research_application_service
from trendora.research.exceptions import ResearchNoCoverageError
from trendora.research.models import ResearchRunStatus
from trendora.research.reporting import (
    ResearchReportService,
    build_research_report_service,
)

from trendora.api.errors import register_error_handlers
from trendora.api.models import ForecastResponse, to_forecast_response
from trendora.api.research_models import (
    ResearchRequest,
    ResearchResponse,
    to_research_response,
)
from trendora.api.research_report_models import (
    ResearchReportRequest,
    ResearchReportResponse,
    to_report_response,
)

logger = logging.getLogger("trendora.api.app")


class ReportSummaryResponse(BaseModel):
    """Metadata-only summary of one persisted report (no JSONB payload)."""

    id: str
    created_at: str
    status: str
    topic: str
    markets: list[str]
    source_codes: list[str]
    date_from: str
    date_to: str


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency: opens a database session for report reads."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def _persist_research_report(
    payload: ResearchReportRequest,
    response: ResearchReportResponse,
) -> None:
    """Best-effort append-only persistence of a completed report snapshot.

    Persistence is strictly optional: a missing ``DATABASE_URL`` or any insert
    failure is logged and swallowed so the HTTP response is never affected.
    """
    try:
        if not get_settings().database_url:
            return
        session = get_session_factory()()
        try:
            record = ResearchReportRecord(
                status=response.status,
                topic=payload.topic,
                markets=list(payload.markets) if payload.markets else list(response.research.query.markets),
                source_codes=list(payload.sources),
                date_from=payload.date_from,
                date_to=payload.date_to,
                report=response.model_dump(mode="json"),
            )
            session.add(record)
            session.commit()
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001 — best-effort only
        logger.warning("Failed to persist research report: %s", exc)


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

    Builds a YouTube client only when ``YOUTUBE_API_KEY`` is configured, and a
    Facebook client only when both ``META_ACCESS_TOKEN`` and
    ``META_GRAPH_API_VERSION`` are configured. If a source's settings are
    missing, no runtime retriever is registered; an available source then
    surfaces as a ``research_source_not_configured`` error. Each owned client
    closes exactly once. Tests override this dependency.
    """

    settings = get_settings()
    with ExitStack() as stack:
        youtube_client = (
            YouTubeClient(settings.youtube_api_key) if settings.youtube_api_key else None
        )
        if youtube_client is not None:
            stack.callback(youtube_client.close)
        facebook_client = (
            FacebookPublicClient(
                settings.meta_access_token, settings.meta_graph_api_version
            )
            if settings.meta_access_token and settings.meta_graph_api_version
            else None
        )
        if facebook_client is not None:
            stack.callback(facebook_client.close)
        service = build_research_application_service(
            youtube_client=youtube_client, facebook_client=facebook_client
        )
        yield service


def get_research_report_service() -> Generator[ResearchReportService, None, None]:
    """FastAPI dependency: report pipeline service.

    Fails fast when AI configuration is missing (missing provider config is
    never ``no_evidence`` or empty AI output). Owns one YouTube client, one
    Facebook client, and one shared HTTP client for the three AI adapters;
    each closes exactly once. Tests override this dependency.
    """

    settings = get_settings()
    config = build_ai_provider_config(
        provider=settings.ai_provider,
        model=settings.ai_model,
        endpoint_url=settings.ai_endpoint_url,
        api_key=settings.ai_api_key,
    )
    with ExitStack() as stack:
        youtube_client = (
            YouTubeClient(settings.youtube_api_key) if settings.youtube_api_key else None
        )
        if youtube_client is not None:
            stack.callback(youtube_client.close)
        facebook_client = (
            FacebookPublicClient(
                settings.meta_access_token, settings.meta_graph_api_version
            )
            if settings.meta_access_token and settings.meta_graph_api_version
            else None
        )
        if facebook_client is not None:
            stack.callback(facebook_client.close)
        http = httpx.Client(timeout=config.timeout_seconds)
        stack.callback(http.close)
        service = build_research_report_service(
            youtube_client=youtube_client,
            facebook_client=facebook_client,
            http_client=http,
            config=config,
        )
        yield service


def create_app() -> FastAPI:
    app = FastAPI(
        title="Trendora API",
        description=(
            "Trendora read-model API. V1 exposes the GitHub forecast product "
            "(M10) and the source-routed research workflow (M15): query + "
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
        summary="Run source-routed research",
        description=(
            "Run one synchronous research request: topic + market + date "
            "window → capability coverage → configured source retrievers "
            "(YouTube, a single Facebook Page, or both combined) → "
            "normalized in-memory references. Returns the ResearchRun state "
            "(query, coverage, execution status, references). No persistence, "
            "no AI, no derived metrics."
        ),
        responses={
            422: {"description": "Invalid research request, or no requested source has usable coverage"},
            503: {"description": "Source is available but no runtime retriever is configured"},
            502: {"description": "Upstream source failure"},
        },
    )
    def research(
        payload: ResearchRequest,
        service: ResearchApplicationService = Depends(get_research_application_service),
    ) -> ResearchResponse:
        query = adapt_research_request(payload.model_dump())
        run = service.execute(
            topic=query.topic,
            markets=query.markets,
            date_from=query.date_from,
            date_to=query.date_to,
            sources=query.source_codes,
            result_limit=query.result_limit,
            facebook_page_id=query.facebook_page_id,
        )
        if run.status is ResearchRunStatus.BLOCKED:
            raise ResearchNoCoverageError(
                "no requested source can satisfy the required capability"
            )
        return to_research_response(run)

    @app.post(
        "/api/v1/research/report",
        response_model=ResearchReportResponse,
        summary="Run full research report",
        description=(
            "Run one synchronous full research report: research → evidence → "
            "patterns → grounded interpretation → gaps/opportunities → ideas/"
            "briefs. Returns the validated report with provenance at every "
            "stage. Requires AI provider configuration; no persistence, no "
            "ranking, no performance claims."
        ),
        responses={
            422: {"description": "Invalid research request, or no requested source has usable coverage"},
            503: {"description": "AI provider is not configured"},
            502: {"description": "AI provider or upstream failure / invalid AI response"},
        },
    )
    def research_report(
        payload: ResearchReportRequest,
        service: ResearchReportService = Depends(get_research_report_service),
    ) -> ResearchReportResponse:
        query = adapt_research_request(payload.model_dump())
        report = service.build_report(
            topic=query.topic,
            markets=query.markets,
            date_from=query.date_from,
            date_to=query.date_to,
            sources=query.source_codes,
            result_limit=query.result_limit,
            facebook_page_id=query.facebook_page_id,
        )
        response = to_report_response(report)
        _persist_research_report(payload, response)
        return response

    @app.get(
        "/api/v1/research/reports",
        response_model=list[ReportSummaryResponse],
        summary="List persisted research reports",
        description=(
            "Return a paginated list of all persisted reports ordered by "
            "creation time descending. Summaries only — no full JSONB payloads."
        ),
    )
    def list_research_reports(
        limit: int = Query(default=50, ge=1, le=100, description="Max records to return"),
        offset: int = Query(default=0, ge=0, description="Offset for pagination"),
        session: Session = Depends(get_session),
    ) -> list[ReportSummaryResponse]:
        from trendora.research.repository import get_report_records

        summaries, _total = get_report_records(session, limit=limit, offset=offset)
        return [ReportSummaryResponse(**summary) for summary in summaries]

    @app.get(
        "/api/v1/research/reports/{report_id}",
        response_model=ResearchReportResponse,
        summary="Fetch single report by ID",
        description=(
            "Return the full report snapshot including evidence, interpretation, "
            "strategy, and ideation."
        ),
        responses={404: {"description": "Report not found"}},
    )
    def get_single_report(
        report_id: str,
        session: Session = Depends(get_session),
    ) -> ResearchReportResponse:
        from trendora.research.repository import get_report_record_by_id

        full_report = get_report_record_by_id(session, report_id)
        if full_report is None:
            raise HTTPException(status_code=404, detail="Report not found")
        return ResearchReportResponse(**full_report["report"])

    return app
