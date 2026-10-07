"""FastAPI application exposing the M10 GitHub forecast product and research.

Forecast:
  HTTP → this route → M10 GitHubForecastProduct → M5 / M6A / M7 → response

Research:
  HTTP → this route → research application service → ResearchQuery →
  capability resolution → configured source retriever → ResearchRun → response

Thin adapters only: no forecasting/retrieval logic, no SQL, no connectors in
the route layer, no persistence, no rate limiting. Authentication is the one
exception: every route except ``/health`` requires an active local membership
(``require_member``); the admin router adds ``require_admin``. Report reads
carry the rolling 30-day visibility cutoff for non-admins.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import ExitStack
from datetime import datetime
from uuid import UUID, uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from trendora.analytics.service import AnalyticsService
from trendora.config import get_settings
from trendora.connectors.facebook.client import FacebookPublicClient
from trendora.connectors.web_search.serper_gateway import SerperGateway
from trendora.connectors.youtube.client import YouTubeClient
from trendora.db.session import get_session_factory
from trendora.forecasting.exceptions import ForecastingValidationError
from trendora.product import V1_METRICS, GitHubForecastProduct, GitHubForecastRequest
from trendora.research.ai_provider import build_ai_provider_config
from trendora.research.adapter import adapt_research_request
from trendora.research.application import ResearchApplicationService, build_research_application_service
from trendora.research.exceptions import ResearchAIProviderNotConfiguredError, ResearchNoCoverageError
from trendora.research.models import ResearchRunStatus
from trendora.research.recovery import issue_recovery_receipt
from trendora.research.reporting import (
    ResearchReportService,
    build_research_report_service,
)
from trendora.research.repository import insert_report_snapshot
from trendora.retention import report_source_deadline

from trendora.api.admin import admin_router
from trendora.api.auth import (
    Member,
    get_utc_now,
    report_visible_from,
    require_member,
)
from trendora.api.deps import get_session
from trendora.api.errors import register_error_handlers
from trendora.api.models import ForecastResponse, to_forecast_response
from trendora.api.report_save import ReportExpiredError, report_save_router
from trendora.api.report_snapshot import SNAPSHOT_FIELDS, snapshot_fingerprint
from trendora.api.research_models import (
    ResearchRequest,
    ResearchResponse,
    to_research_response,
)
from trendora.api.research_report_models import (
    PersistenceOutcomeResponse,
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
    snapshot_origin: str = "legacy_unclassified"


def _persist_research_report(
    payload: ResearchReportRequest,
    response: ResearchReportResponse,
    actor_id: UUID,
) -> PersistenceOutcomeResponse:
    """Best-effort append-only persistence with an explicit outcome.

    Persistence is strictly optional: a missing ``DATABASE_URL`` or any insert
    failure never affects the HTTP generation response. The outcome is derived
    from the normalized query, fingerprinted canonically, and keyed on the
    authenticated actor plus a stable request id so a later recovery by the
    same actor can acknowledge it.
    """
    request_id = uuid4()
    snapshot = _snapshot_projection(response)
    fingerprint = snapshot_fingerprint(snapshot)
    now = get_utc_now()
    source_expires_at = report_source_deadline(snapshot, now=now)
    recovery_receipt = None
    query = response.research.query
    outcome_meta = {
        "topic": query.topic,
        "markets": list(query.markets),
        "source_codes": list(query.sources),
        "date_from": query.date_from,
        "date_to": query.date_to,
    }
    try:
        settings = get_settings()
        if source_expires_at is not None and source_expires_at > now:
            recovery_receipt = issue_recovery_receipt(
                actor_id=actor_id, request_id=request_id, fingerprint=fingerprint,
                source_expires_at=source_expires_at,
                signing_key=getattr(settings, "report_recovery_signing_key", None),
            )
        if not settings.database_url:
            return PersistenceOutcomeResponse(
                status="failed",
                request_id=str(request_id),
                report_id=None,
                snapshot_origin="server_generated",
                error_code="persistence_unconfigured",
                recovery_receipt=recovery_receipt,
            )
        session = get_session_factory()()
        try:
            record = insert_report_snapshot(
                session,
                snapshot=snapshot,
                fingerprint=fingerprint,
                request_id=request_id,
                created_by=actor_id,
                origin="server_generated",
                source_expires_at=source_expires_at,
                status=response.status,
                **outcome_meta,
            )
            # Copy the generated id before commit: commit expires the ORM
            # instance, so reading it afterwards would trigger a reload.
            report_id = str(record.id)
            session.commit()
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001 - best-effort only
        logger.warning("Failed to persist research report: %s", type(exc).__name__)
        return PersistenceOutcomeResponse(
            status="unknown",
            request_id=str(request_id),
            report_id=None,
            snapshot_origin="server_generated",
            error_code="persistence_uncertain",
            recovery_receipt=recovery_receipt,
        )
    return PersistenceOutcomeResponse(
        status="saved",
        request_id=str(request_id),
        report_id=report_id,
        snapshot_origin="server_generated",
        error_code=None,
        recovery_receipt=recovery_receipt,
    )


def _snapshot_projection(response: ResearchReportResponse) -> dict:
    """The immutable six-field snapshot, excluding persistence metadata."""
    dumped = response.model_dump(mode="json")
    return {field: dumped.get(field) for field in SNAPSHOT_FIELDS}


def _build_serp_gateway(settings) -> SerperGateway | None:
    """Build the web-search gateway when enabled and configured, else ``None``."""
    enabled = getattr(settings, "web_search_enabled", True)
    api_key = getattr(settings, "serper_api_key", None)
    if enabled and api_key:
        return SerperGateway(api_key)
    return None


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

    Builds a YouTube client only when ``YOUTUBE_API_KEY`` is configured, a
    Facebook client only when both ``META_ACCESS_TOKEN`` and
    ``META_GRAPH_API_VERSION`` are configured, and a Serper web-search gateway
    only when ``TRENDORA_WEB_SEARCH_ENABLED`` is true and ``SERPER_API_KEY`` is
    set. If a source's settings are missing, no runtime retriever is registered;
    an available source then surfaces as a ``research_source_not_configured``
    error. Each owned client closes exactly once. Tests override this dependency.
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
        serp_gateway = _build_serp_gateway(settings)
        if serp_gateway is not None:
            stack.callback(serp_gateway.close)
        service = build_research_application_service(
            youtube_client=youtube_client,
            facebook_client=facebook_client,
            serp_gateway=serp_gateway,
        )
        yield service


def get_research_report_service(
    payload: ResearchReportRequest | None = None,
) -> Generator[ResearchReportService, None, None]:
    """Own source clients, research interpretation, and optional content adapters."""

    settings = get_settings()
    config = None
    content_tools = payload.include_content_tools if payload is not None else None
    try:
        config = build_ai_provider_config(
            provider=settings.ai_provider,
            model=settings.ai_model,
            endpoint_url=settings.ai_endpoint_url,
            api_key=settings.ai_api_key,
        )
    except ResearchAIProviderNotConfiguredError:
        if content_tools is None:
            raise
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
        serp_gateway = _build_serp_gateway(settings)
        if serp_gateway is not None:
            stack.callback(serp_gateway.close)
        http = None
        if config is not None:
            http = httpx.Client(timeout=config.timeout_seconds)
            stack.callback(http.close)
        service = build_research_report_service(
            youtube_client=youtube_client,
            facebook_client=facebook_client,
            serp_gateway=serp_gateway,
            http_client=http,
            config=config,
        )
        yield service


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.app_env.lower() == "production" and not settings.supabase_url:
        raise RuntimeError(
            "SUPABASE_URL must be configured when APP_ENV=production; "
            "refusing to start without authentication"
        )
    app = FastAPI(
        title="Trendora API",
        description=(
            "Trendora read-model API. V1 exposes the GitHub forecast product "
            "(M10) and the source-routed research workflow (M15): query + "
            "capability coverage + normalized in-memory references. Every "
            "route except /health requires a Supabase access token with an "
            "active local membership."
        ),
    )
    register_error_handlers(app)
    app.include_router(admin_router)
    app.include_router(report_save_router)
    # Imported here: trendora.api.planner imports trendora.planner, which
    # imports trendora.api.errors and re-enters this module while the
    # trendora.api package is still initializing.
    from trendora.api.planner import planner_router

    app.include_router(planner_router)

    @app.get(
        "/health",
        summary="Liveness probe",
        description="Unauthenticated health probe used by the platform.",
    )
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(
        "/api/v1/forecasts/github/{content_item_id}",
        response_model=ForecastResponse,
        summary="GitHub repository forecast",
        dependencies=[Depends(require_member)],
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
        dependencies=[Depends(require_member)],
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
        summary="Run research with optional content tools",
        dependencies=[Depends(require_member)],
        description=(
            "Collect sources and synthesize research with grounded interpretation, "
            "falling back to labeled source excerpts if interpretation is unavailable. "
            "Explicit include_content_tools=false skips content stages; true adds optional "
            "grounded strategy and ideation. Omission preserves the legacy pipeline. "
            "Generation returns an explicit best-effort save outcome."
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
        member: Member = Depends(require_member),
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
            include_content_tools=payload.include_content_tools,
        )
        response = to_report_response(report)
        response.persistence = _persist_research_report(payload, response, member.user_id)
        return response

    @app.get(
        "/api/v1/research/reports",
        response_model=list[ReportSummaryResponse],
        summary="List persisted research reports",
        description=(
            "Return a paginated list of persisted reports ordered by "
            "creation time descending, newest first. Summaries only, no "
            "full JSONB payloads. Non-admins only see reports from the "
            "rolling 30-day window; admins see all of them."
        ),
    )
    def list_research_reports(
        limit: int = Query(default=50, ge=1, le=100, description="Max records to return"),
        offset: int = Query(default=0, ge=0, description="Offset for pagination"),
        session: Session = Depends(get_session),
        member: Member = Depends(require_member),
        now: datetime = Depends(get_utc_now),
    ) -> list[ReportSummaryResponse]:
        from trendora.research.repository import get_report_records

        summaries, _total = get_report_records(
            session,
            limit=limit,
            offset=offset,
            visible_from=report_visible_from(member, now),
        )
        return [ReportSummaryResponse(**summary) for summary in summaries]

    @app.get(
        "/api/v1/research/reports/{report_id}",
        response_model=ResearchReportResponse,
        summary="Fetch single report by ID",
        description=(
            "Return the full report snapshot including evidence, interpretation, "
            "strategy, and ideation. The same rolling 30-day visibility rule "
            "as the list route applies to non-admins."
        ),
        responses={404: {"description": "Report not found"}},
    )
    def get_single_report(
        report_id: str,
        session: Session = Depends(get_session),
        member: Member = Depends(require_member),
        now: datetime = Depends(get_utc_now),
    ) -> ResearchReportResponse:
        from trendora.research.repository import get_report_record_by_id

        full_report = get_report_record_by_id(
            session,
            report_id,
            visible_from=report_visible_from(member, now),
        )
        if full_report is None:
            raise HTTPException(status_code=404, detail="Report not found")
        if full_report.get("status") == "source_data_expired" or (
            full_report["report"].get("status") == "source_data_expired"
        ):
            raise ReportExpiredError("This report's source data has expired and was removed.")
        response = ResearchReportResponse(**full_report["report"])
        response.persistence = PersistenceOutcomeResponse(
            status="saved",
            request_id=None,
            report_id=full_report["id"],
            snapshot_origin=full_report.get("snapshot_origin", "legacy_unclassified"),
            error_code=None,
        )
        return response

    return app
