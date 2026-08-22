"""Forecasting baseline tests. No database, no source APIs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from trendora.analytics.exceptions import AnalyticsQueryError
from trendora.analytics.models import MetricObservation, MetricSeries, SubjectKind
from trendora.analytics.repository import InMemoryAnalyticsRepository, ObservationQuery
from trendora.analytics.service import AnalyticsService
from trendora.forecasting import (
    EvaluationRequest,
    ForecastModel,
    ForecastRequest,
    ForecastingService,
    ForecastingValidationError,
    InsufficientHistoryError,
)
from trendora.forecasting.service import forecast_series
from trendora.reference import SOURCE_IDS
from tests.fixtures.analytics_observations import GOLDEN_OBSERVATIONS, T15, YT_VIDEO_ID

UTC = timezone.utc
SUBJECT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
DAY = timedelta(days=1)


def _obs(value: int, at: datetime, snapshot: int) -> MetricObservation:
    return MetricObservation(
        snapshot_id=UUID(int=snapshot),
        source_code="youtube",
        source_id=SOURCE_IDS["youtube"],
        metric_name="view_count",
        metric_value=value,
        observed_at=at,
        collected_at=at,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=SUBJECT,
        content_external_id="m6a-video",
        content_type="video",
    )


def _series(*pairs: tuple[int, datetime]) -> MetricSeries:
    rows = tuple(_obs(value, at, i + 1) for i, (value, at) in enumerate(pairs))
    return MetricSeries(observations=rows, source_code="youtube", metric_name="view_count")


def _query() -> ObservationQuery:
    return ObservationQuery(
        source_code="youtube",
        metric_name="view_count",
        content_item_id=SUBJECT,
    )


def _request(**kwargs) -> ForecastRequest:
    payload = dict(
        query=_query(),
        model=ForecastModel.NAIVE,
        horizon=3,
        interval=DAY,
    )
    payload.update(kwargs)
    return ForecastRequest(**payload)


def test_naive_multi_step_and_timestamps() -> None:
    t0 = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    series = _series((10, t0), (12, t0 + DAY), (15, t0 + DAY * 2))
    result = forecast_series(series, _request(horizon=3, interval=DAY))
    assert [point.value for point in result.points] == [15.0, 15.0, 15.0]
    assert [point.at for point in result.points] == [
        datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
        datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
        datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
    ]
    assert result.origin == "trendora_forecast"
    assert result.history_count == 3
    assert result.history_end == t0 + DAY * 2


def test_naive_one_observation() -> None:
    t0 = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    result = forecast_series(_series((10, t0)), _request(horizon=3, interval=DAY))
    assert [point.value for point in result.points] == [10.0, 10.0, 10.0]
    assert [point.at for point in result.points] == [
        datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
        datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
    ]


def test_moving_average_recursive_example() -> None:
    t0 = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    series = _series((10, t0), (20, t0 + DAY), (30, t0 + DAY * 2))
    result = forecast_series(
        series,
        _request(model=ForecastModel.MOVING_AVERAGE, window=2, horizon=3, interval=DAY),
    )
    assert [point.value for point in result.points] == [25.0, 27.5, 26.25]


def test_moving_average_exact_window_size() -> None:
    t0 = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    series = _series((10, t0), (20, t0 + DAY))
    result = forecast_series(
        series,
        _request(model=ForecastModel.MOVING_AVERAGE, window=2, horizon=1, interval=DAY),
    )
    assert result.points[0].value == 15.0


def test_ses_level_and_multi_step() -> None:
    t0 = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    series = _series((10, t0), (20, t0 + DAY), (30, t0 + DAY * 2))
    result = forecast_series(
        series,
        _request(
            model=ForecastModel.SIMPLE_EXPONENTIAL_SMOOTHING,
            alpha=0.5,
            horizon=3,
            interval=DAY,
        ),
    )
    assert [point.value for point in result.points] == [22.5, 22.5, 22.5]


def test_ses_one_observation_equals_that_value() -> None:
    t0 = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    result = forecast_series(
        _series((10, t0)),
        _request(model=ForecastModel.SIMPLE_EXPONENTIAL_SMOOTHING, alpha=1.0, horizon=2, interval=DAY),
    )
    assert [point.value for point in result.points] == [10.0, 10.0]


def test_empty_series_is_rejected() -> None:
    with pytest.raises(InsufficientHistoryError, match="at least one"):
        forecast_series(
            MetricSeries(observations=(), source_code="youtube", metric_name="view_count"),
            _request(),
        )


def test_moving_average_insufficient_history() -> None:
    t0 = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    with pytest.raises(InsufficientHistoryError, match="window 3"):
        forecast_series(
            _series((10, t0), (20, t0 + DAY)),
            _request(model=ForecastModel.MOVING_AVERAGE, window=3, horizon=1, interval=DAY),
        )


def test_does_not_fill_missing_history_points() -> None:
    t0 = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    series = _series((1, t0), (3, t0 + DAY * 2))
    result = forecast_series(series, _request(horizon=1, interval=DAY))
    assert result.history_count == 2
    assert [point.value for point in result.points] == [3.0]


def test_orders_by_m5_semantics_not_input_order() -> None:
    t0 = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    later = _obs(15, t0 + DAY, 2)
    earlier = _obs(10, t0, 1)
    series = MetricSeries(observations=(later, earlier), source_code="youtube", metric_name="view_count")
    result = forecast_series(series, _request(horizon=1, interval=DAY))
    assert result.points[0].value == 15.0
    assert result.history_start == t0
    assert result.history_end == t0 + DAY


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"horizon": 0}, "horizon"),
        ({"interval": timedelta(0)}, "interval"),
        ({"interval": timedelta(days=-1)}, "interval"),
        ({"model": ForecastModel.MOVING_AVERAGE}, "window"),
        ({"model": ForecastModel.MOVING_AVERAGE, "window": 0}, "window"),
        ({"model": ForecastModel.SIMPLE_EXPONENTIAL_SMOOTHING}, "alpha"),
        ({"model": ForecastModel.SIMPLE_EXPONENTIAL_SMOOTHING, "alpha": 0.0}, "alpha"),
        ({"model": ForecastModel.SIMPLE_EXPONENTIAL_SMOOTHING, "alpha": 1.1}, "alpha"),
        ({"window": 2}, "naive does not use window"),
        ({"alpha": 0.5}, "naive does not use alpha"),
    ],
)
def test_invalid_request_params(kwargs: dict, match: str) -> None:
    t0 = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    with pytest.raises(ForecastingValidationError, match=match):
        forecast_series(_series((10, t0)), _request(**kwargs))


def test_naive_datetime_on_history_is_rejected() -> None:
    naive = datetime(2026, 8, 11, 12, 0)
    with pytest.raises(ForecastingValidationError, match="timezone-aware"):
        forecast_series(_series((10, naive)), _request())


def test_service_uses_m5_series_not_zeros() -> None:
    analytics = AnalyticsService(InMemoryAnalyticsRepository(GOLDEN_OBSERVATIONS))
    service = ForecastingService(analytics)
    result = service.forecast(
        ForecastRequest(
            query=ObservationQuery(
                source_code="youtube",
                metric_name="view_count",
                content_item_id=YT_VIDEO_ID,
            ),
            model=ForecastModel.NAIVE,
            horizon=2,
            interval=DAY,
        )
    )
    assert [point.value for point in result.points] == [200.0, 200.0]
    assert result.points[0].at == T15 + DAY
    assert result.points[1].at == T15 + DAY * 2
    evaluation = service.evaluate(
        EvaluationRequest(
            query=ObservationQuery(
                source_code="youtube",
                metric_name="view_count",
                content_item_id=YT_VIDEO_ID,
            ),
            model=ForecastModel.NAIVE,
            holdout=1,
            interval=DAY,
        )
    )
    assert evaluation.training_observation_count == 2
    assert evaluation.test_observation_count == 1
    assert evaluation.mae == 50.0


def test_service_rejects_naive_query_datetime() -> None:
    service = ForecastingService(AnalyticsService(InMemoryAnalyticsRepository(GOLDEN_OBSERVATIONS)))
    with pytest.raises(AnalyticsQueryError, match="timezone-aware"):
        service.forecast(
            ForecastRequest(
                query=ObservationQuery(
                    source_code="youtube",
                    metric_name="view_count",
                    content_item_id=YT_VIDEO_ID,
                    observed_from=datetime(2026, 8, 21, 12, 0),
                ),
                model=ForecastModel.NAIVE,
                horizon=1,
                interval=DAY,
            )
        )


def test_subject_and_source_are_required() -> None:
    t0 = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    with pytest.raises(ForecastingValidationError, match="source_code"):
        forecast_series(
            _series((10, t0)),
            _request(query=ObservationQuery(metric_name="view_count", content_item_id=SUBJECT)),
        )
    with pytest.raises(ForecastingValidationError, match="metric_name"):
        forecast_series(
            _series((10, t0)),
            _request(query=ObservationQuery(source_code="youtube", content_item_id=SUBJECT)),
        )
    with pytest.raises(ForecastingValidationError, match="content_item_id or publisher_id"):
        forecast_series(
            _series((10, t0)),
            _request(query=ObservationQuery(source_code="youtube", metric_name="view_count")),
        )
