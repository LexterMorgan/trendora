"""Exception-to-HTTP mapping for the V1 forecast API (docs/13 §10).

Small error envelope: ``{"error": {"code": ..., "message": ...}}``. Only the
status codes/codes justified by the M11A contract are emitted:
422 invalid_metric / invalid_request / forecast_insufficient_history,
404 (unused by this adapter, see docs/13 §10.1), 500 analytics_query_error /
internal_error. No 401/403/409/503.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from trendora.analytics.exceptions import AnalyticsQueryError
from trendora.forecasting.exceptions import ForecastingValidationError, InsufficientHistoryError


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
    # Malformed path/query parameters (e.g. non-UUID content_item_id).
    return _error(422, "invalid_request", "request validation failed")


async def _handle_unexpected(_request: Request, _exc: Exception) -> JSONResponse:
    return _error(500, "internal_error", "internal server error")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(InsufficientHistoryError, _handle_insufficient_history)
    app.add_exception_handler(ForecastingValidationError, _handle_forecasting_validation)
    app.add_exception_handler(AnalyticsQueryError, _handle_analytics_query)
    app.add_exception_handler(RequestValidationError, _handle_request_validation)
    app.add_exception_handler(Exception, _handle_unexpected)
