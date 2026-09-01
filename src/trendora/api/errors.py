"""Exception-to-HTTP mapping for the Trendora API.

Small error envelope: ``{"error": {"code": ..., "message": ...}}``.

Forecast (docs/13 §10): 422 invalid_metric / invalid_request /
forecast_insufficient_history, 500 analytics_query_error / internal_error.

Research (docs/17): 422 invalid_research_request / research_no_coverage,
503 research_source_not_configured, 502 research_upstream_error.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from trendora.analytics.exceptions import AnalyticsQueryError
from trendora.connectors.youtube.exceptions import YouTubeConnectorError
from trendora.forecasting.exceptions import ForecastingValidationError, InsufficientHistoryError
from trendora.research.exceptions import (
    ResearchNoCoverageError,
    ResearchSourceNotConfiguredError,
    ResearchValidationError,
)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


async def _handle_insufficient_history(_request: Request, exc: InsufficientHistoryError) -> JSONResponse:
    return _error(422, "forecast_insufficient_history", str(exc))


async def _handle_forecasting_validation(_request: Request, exc: ForecastingValidationError) -> JSONResponse:
    # From the API path this only fires for an unsupported metric value.
    return _error(422, "invalid_metric", str(exc))


async def _handle_analytics_query(_request: Request, exc: AnalyticsQueryError) -> JSONResponse:
    return _error(500, "analytics_query_error", str(exc))


async def _handle_request_validation(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    # Malformed/structurally invalid request body or parameters.
    return _error(422, "invalid_request", "request validation failed")


async def _handle_unexpected(_request: Request, _exc: Exception) -> JSONResponse:
    return _error(500, "internal_error", "internal server error")


async def _handle_research_validation(_request: Request, exc: ResearchValidationError) -> JSONResponse:
    return _error(422, "invalid_research_request", str(exc))


async def _handle_research_no_coverage(_request: Request, exc: ResearchNoCoverageError) -> JSONResponse:
    return _error(422, "research_no_coverage", str(exc))


async def _handle_research_source_not_configured(
    _request: Request, exc: ResearchSourceNotConfiguredError
) -> JSONResponse:
    return _error(503, "research_source_not_configured", str(exc))


async def _handle_youtube_upstream(_request: Request, exc: YouTubeConnectorError) -> JSONResponse:
    return _error(502, "research_upstream_error", str(exc))


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(InsufficientHistoryError, _handle_insufficient_history)
    app.add_exception_handler(ForecastingValidationError, _handle_forecasting_validation)
    app.add_exception_handler(AnalyticsQueryError, _handle_analytics_query)
    app.add_exception_handler(RequestValidationError, _handle_request_validation)
    app.add_exception_handler(ResearchValidationError, _handle_research_validation)
    app.add_exception_handler(ResearchNoCoverageError, _handle_research_no_coverage)
    app.add_exception_handler(
        ResearchSourceNotConfiguredError, _handle_research_source_not_configured
    )
    app.add_exception_handler(YouTubeConnectorError, _handle_youtube_upstream)
    app.add_exception_handler(Exception, _handle_unexpected)
