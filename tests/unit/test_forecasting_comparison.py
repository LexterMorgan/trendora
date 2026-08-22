"""M6C naive-vs-challenger comparison. No database."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from trendora.analytics.models import MetricObservation, MetricSeries, SubjectKind
from trendora.analytics.repository import InMemoryAnalyticsRepository, ObservationQuery
from trendora.analytics.service import AnalyticsService
from trendora.forecasting import (
    ComparisonRequest,
    EvaluationRequest,
    ForecastModel,
    ForecastingService,
    ForecastingValidationError,
    InsufficientHistoryError,
)
from trendora.forecasting.service import compare_series, evaluate_series
from trendora.reference import SOURCE_IDS
from tests.fixtures.analytics_observations import GOLDEN_OBSERVATIONS, YT_VIDEO_ID

UTC = timezone.utc
SUBJECT = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
DAY = timedelta(days=1)


def _obs(value: int, at: datetime, snapshot: int) -> MetricObservation:
    return MetricObservation(
        snapshot_id=UUID(int=snapshot),
        source_code="github",
        source_id=SOURCE_IDS["github"],
        metric_name="stargazer_count",
        metric_value=value,
        observed_at=at,
        collected_at=at,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=SUBJECT,
        content_type="repository",
    )


def _series(values: list[int], times: list[datetime] | None = None) -> MetricSeries:
    if times is None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        times = [start + DAY * i for i in range(len(values))]
    rows = tuple(_obs(value, at, i + 1) for i, (value, at) in enumerate(zip(values, times, strict=True)))
    return MetricSeries(observations=rows, source_code="github", metric_name="stargazer_count")


def _query() -> ObservationQuery:
    return ObservationQuery(
        source_code="github",
        metric_name="stargazer_count",
        content_item_id=SUBJECT,
    )


def _compare(**kwargs) -> ComparisonRequest:
    payload = dict(
        query=_query(),
        challenger=ForecastModel.MOVING_AVERAGE,
        holdout=2,
        interval=DAY,
        window=2,
    )
    payload.update(kwargs)
    return ComparisonRequest(**payload)


def test_naive_vs_moving_average_maes_and_loss() -> None:
    series = _series([10, 12, 14, 16, 18, 20])
    result = compare_series(series, _compare(window=2))
    naive = evaluate_series(
        series,
        EvaluationRequest(query=_query(), model=ForecastModel.NAIVE, holdout=2, interval=DAY),
    )
    challenger = evaluate_series(
        series,
        EvaluationRequest(
            query=_query(),
            model=ForecastModel.MOVING_AVERAGE,
            holdout=2,
            interval=DAY,
            window=2,
        ),
    )
    assert result.naive_mae == 3.0
    assert result.challenger_mae == 3.75
    assert result.naive_mae == naive.mae
    assert result.challenger_mae == challenger.mae
    assert result.challenger_beats_naive is False
    assert result.training_observation_count == 4
    assert result.test_observation_count == 2
    assert result.training_observation_count == naive.training_observation_count == challenger.training_observation_count
    assert result.holdout_start == naive.holdout_start == challenger.holdout_start
    assert result.holdout_end == naive.holdout_end == challenger.holdout_end
    assert result.origin == "trendora_forecast"


def test_challenger_wins_moving_average() -> None:
    result = compare_series(_series([10, 10, 10, 100, 10, 10]), _compare(window=3))
    assert result.naive_mae == 90.0
    assert result.challenger_mae == 35.0
    assert result.challenger_beats_naive is True


def test_naive_vs_ses_and_tie_is_false() -> None:
    series = _series([10, 12, 14, 16, 18, 20])
    result = compare_series(
        series,
        _compare(
            challenger=ForecastModel.SIMPLE_EXPONENTIAL_SMOOTHING,
            window=None,
            alpha=1.0,
        ),
    )
    assert result.challenger is ForecastModel.SIMPLE_EXPONENTIAL_SMOOTHING
    assert result.naive_mae == result.challenger_mae == 3.0
    assert result.challenger_beats_naive is False


def test_ses_challenger_can_win() -> None:
    result = compare_series(
        _series([10, 10, 10, 100, 10, 10]),
        _compare(
            challenger=ForecastModel.SIMPLE_EXPONENTIAL_SMOOTHING,
            window=None,
            alpha=0.1,
        ),
    )
    assert result.naive_mae == 90.0
    assert result.challenger_mae == 9.0
    assert result.challenger_beats_naive is True


def test_same_holdout_and_irregular_timestamps() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    times = [start, start + timedelta(hours=3), start + timedelta(days=2), start + timedelta(days=5)]
    series = _series([10, 12, 14, 16], times)
    result = compare_series(
        series,
        _compare(
            challenger=ForecastModel.SIMPLE_EXPONENTIAL_SMOOTHING,
            holdout=2,
            window=None,
            alpha=1.0,
        ),
    )
    assert result.holdout == 2
    assert result.training_observation_count == 2
    assert result.test_observation_count == 2
    assert result.holdout_start == times[2]
    assert result.holdout_end == times[3]
    assert result.naive_mae == 3.0


def test_no_future_leakage_matches_evaluate() -> None:
    series = _series([10, 12, 14, 16, 18, 20])
    result = compare_series(series, _compare(window=2))
    leaked_would_use_test = evaluate_series(
        series,
        EvaluationRequest(
            query=_query(),
            model=ForecastModel.MOVING_AVERAGE,
            holdout=2,
            interval=DAY,
            window=2,
        ),
    )
    assert result.challenger_mae == leaked_would_use_test.mae == 3.75


def test_identity_holdout_and_interval_are_required() -> None:
    series = _series([10, 12, 14, 16])
    with pytest.raises(ForecastingValidationError, match="source_code"):
        compare_series(
            series,
            _compare(query=ObservationQuery(metric_name="stargazer_count", content_item_id=SUBJECT)),
        )
    with pytest.raises(ForecastingValidationError, match="metric_name"):
        compare_series(
            series,
            _compare(query=ObservationQuery(source_code="github", content_item_id=SUBJECT)),
        )
    with pytest.raises(ForecastingValidationError, match="content_item_id or publisher_id"):
        compare_series(
            series,
            _compare(query=ObservationQuery(source_code="github", metric_name="stargazer_count")),
        )
    with pytest.raises(ForecastingValidationError, match="holdout"):
        compare_series(series, _compare(holdout=0))
    with pytest.raises(ForecastingValidationError, match="training"):
        compare_series(series, _compare(holdout=4))
    with pytest.raises(ForecastingValidationError, match="interval"):
        compare_series(series, _compare(interval=timedelta(0)))


def test_invalid_challenger_and_params() -> None:
    series = _series([10, 12, 14, 16])
    with pytest.raises(ForecastingValidationError, match="challenger"):
        compare_series(series, _compare(challenger=ForecastModel.NAIVE, window=None))
    with pytest.raises(ForecastingValidationError, match="window"):
        compare_series(
            series,
            _compare(challenger=ForecastModel.MOVING_AVERAGE, window=None),
        )
    with pytest.raises(ForecastingValidationError, match="alpha"):
        compare_series(
            series,
            _compare(
                challenger=ForecastModel.SIMPLE_EXPONENTIAL_SMOOTHING,
                window=None,
                alpha=None,
            ),
        )
    with pytest.raises(ForecastingValidationError, match="alpha"):
        compare_series(series, _compare(window=2, alpha=0.3))
    with pytest.raises(ForecastingValidationError, match="window"):
        compare_series(
            series,
            _compare(
                challenger=ForecastModel.SIMPLE_EXPONENTIAL_SMOOTHING,
                window=2,
                alpha=0.3,
            ),
        )


def test_insufficient_and_empty_history() -> None:
    with pytest.raises(InsufficientHistoryError, match="window 3"):
        compare_series(_series([10, 12, 14, 16]), _compare(window=3, holdout=2))
    empty = MetricSeries(observations=(), source_code="github", metric_name="stargazer_count")
    with pytest.raises(InsufficientHistoryError, match="at least one"):
        compare_series(empty, _compare())


def test_naive_datetime_rejected() -> None:
    naive = datetime(2026, 1, 1)
    with pytest.raises(ForecastingValidationError, match="timezone-aware"):
        compare_series(_series([10, 12, 14], [naive, naive + DAY, naive + DAY * 2]), _compare())


def test_deterministic_and_does_not_mutate_history() -> None:
    series = _series([10, 12, 14, 16, 18, 20])
    before = tuple((row.snapshot_id, row.metric_value, row.observed_at) for row in series.observations)
    request = _compare(window=2)
    first = compare_series(series, request)
    second = compare_series(series, request)
    assert first == second
    after = tuple((row.snapshot_id, row.metric_value, row.observed_at) for row in series.observations)
    assert before == after


def test_service_compare_uses_m5_series() -> None:
    service = ForecastingService(AnalyticsService(InMemoryAnalyticsRepository(GOLDEN_OBSERVATIONS)))
    result = service.compare(
        ComparisonRequest(
            query=ObservationQuery(
                source_code="youtube",
                metric_name="view_count",
                content_item_id=YT_VIDEO_ID,
            ),
            challenger=ForecastModel.SIMPLE_EXPONENTIAL_SMOOTHING,
            holdout=1,
            interval=DAY,
            alpha=1.0,
        )
    )
    assert result.source_code == "youtube"
    assert result.metric_name == "view_count"
    assert result.content_item_id == YT_VIDEO_ID
    assert result.naive_mae == 50.0
    assert result.challenger_mae == 50.0
    assert result.challenger_beats_naive is False
    assert result.training_observation_count == 2
    assert result.test_observation_count == 1
