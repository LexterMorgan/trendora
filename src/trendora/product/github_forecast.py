"""V1 GitHub repository forecast product (M10).

Thin composition over existing M5, M6A, and M7 contracts. No SQL, no
connectors, no persistence, no resampling, no imputation, no new models.

Product contract (M9 / docs/12):
- source = github
- subject = content_item (GitHub repository)
- metric in {stargazer_count, fork_count}
- naive level forecast of the stored metric
- horizon = 4 points, interval = 7 days (a generation/labeling convention,
  not a claim that snapshots follow a weekly grid)
- minimum 4 observations; fewer than 4 is an insufficient-history error
- in-memory result, origin = trendora_forecast
- factual history/freshness/cadence context for future API/dashboard layers
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from trendora.analytics.repository import ObservationQuery
from trendora.analytics.service import AnalyticsService
from trendora.diagnostics.models import CadenceClass
from trendora.diagnostics.service import DiagnosticsService
from trendora.forecasting.exceptions import ForecastingValidationError, InsufficientHistoryError
from trendora.forecasting.models import ForecastModel, ForecastPoint, ForecastRequest
from trendora.forecasting.service import ForecastingService

V1_SOURCE = "github"
V1_METRICS = frozenset({"stargazer_count", "fork_count"})
V1_HORIZON = 4
V1_INTERVAL = timedelta(days=7)
V1_MIN_OBSERVATIONS = 4
V1_ORIGIN = "trendora_forecast"


@dataclass(frozen=True, kw_only=True)
class GitHubForecastRequest:
    """V1 request: one GitHub repository content_item + one approved metric.

    ``publisher_id`` is accepted on the request only so the product can
    reject publisher subjects explicitly. The V1 product forecasts
    ``content_item`` subjects only.
    """

    metric_name: str
    content_item_id: UUID | None = None
    publisher_id: UUID | None = None
    source_code: str = V1_SOURCE


@dataclass(frozen=True, kw_only=True)
class GitHubForecastResult:
    """In-memory V1 product result.

    ``origin`` is ``trendora_forecast``: a Trendora-derived value, never an
    official GitHub field. ``cadence`` / ``irregular_cadence`` are factual M7
    observations (history spacing), not a quality or forecastability score.
    ``latest_observed_at`` equals ``history_end`` and is exposed for freshness
    display; no freshness threshold is defined by this product.
    """

    source_code: str
    metric_name: str
    content_item_id: UUID
    content_external_id: str | None
    model: ForecastModel
    horizon: int
    interval: timedelta
    origin: str
    points: tuple[ForecastPoint, ...]
    observation_count: int
    history_start: datetime
    history_end: datetime
    latest_observed_at: datetime
    cadence: CadenceClass
    irregular_cadence: bool


class GitHubForecastProduct:
    """V1 GitHub forecast entry point. Composes M5/M6A/M7; writes nothing."""

    def __init__(self, analytics: AnalyticsService) -> None:
        self._analytics = analytics
        self._forecasting = ForecastingService(analytics)
        self._diagnostics = DiagnosticsService(analytics)

    def forecast(self, request: GitHubForecastRequest) -> GitHubForecastResult:
        _validate_request(request)
        query = ObservationQuery(
            source_code=V1_SOURCE,
            metric_name=request.metric_name,
            content_item_id=request.content_item_id,
        )
        series = self._analytics.get_metric_series(query)
        if len(series) < V1_MIN_OBSERVATIONS:
            raise InsufficientHistoryError(
                f"GitHub V1 forecast requires at least {V1_MIN_OBSERVATIONS} observations; "
                f"found {len(series)}"
            )
        forecast = self._forecasting.forecast(
            ForecastRequest(
                query=query,
                model=ForecastModel.NAIVE,
                horizon=V1_HORIZON,
                interval=V1_INTERVAL,
            )
        )
        diagnostics = self._diagnostics.diagnose(query)
        assert request.content_item_id is not None
        return GitHubForecastResult(
            source_code=forecast.source_code,
            metric_name=forecast.metric_name,
            content_item_id=request.content_item_id,
            content_external_id=series.observations[0].content_external_id,
            model=forecast.model,
            horizon=forecast.horizon,
            interval=forecast.interval,
            origin=forecast.origin,
            points=forecast.points,
            observation_count=forecast.history_count,
            history_start=forecast.history_start,
            history_end=forecast.history_end,
            latest_observed_at=forecast.history_end,
            cadence=diagnostics.cadence,
            irregular_cadence=diagnostics.cadence is CadenceClass.VARIABLE,
        )


def _validate_request(request: GitHubForecastRequest) -> None:
    if request.source_code != V1_SOURCE:
        raise ForecastingValidationError(
            f"GitHub V1 forecast supports source {V1_SOURCE!r}; got {request.source_code!r}"
        )
    if request.metric_name not in V1_METRICS:
        raise ForecastingValidationError(
            f"GitHub V1 forecast supports metrics {sorted(V1_METRICS)}; got {request.metric_name!r}"
        )
    if request.publisher_id is not None:
        raise ForecastingValidationError(
            "GitHub V1 forecast forecasts content_item subjects only; "
            "publisher subjects are unsupported"
        )
    if request.content_item_id is None:
        raise ForecastingValidationError("GitHub V1 forecast requires content_item_id")
