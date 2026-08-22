"""Chronological holdout MAE tests. No database."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from trendora.analytics.models import MetricObservation, MetricSeries, SubjectKind
from trendora.analytics.repository import ObservationQuery
from trendora.forecasting import (
    EvaluationRequest,
    ForecastModel,
    ForecastingValidationError,
    InsufficientHistoryError,
)
from trendora.forecasting.service import evaluate_series
from trendora.reference import SOURCE_IDS

UTC = timezone.utc
SUBJECT = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
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


def _eval(**kwargs) -> EvaluationRequest:
    payload = dict(
        query=ObservationQuery(
            source_code="github",
            metric_name="stargazer_count",
            content_item_id=SUBJECT,
        ),
        model=ForecastModel.NAIVE,
        holdout=2,
        interval=DAY,
    )
    payload.update(kwargs)
    return EvaluationRequest(**payload)


def test_naive_mae_on_documented_holdout() -> None:
    result = evaluate_series(_series([10, 12, 14, 16, 18, 20]), _eval(holdout=2))
    assert result.training_observation_count == 4
    assert result.test_observation_count == 2
    assert result.mae == 3.0
    assert result.model is ForecastModel.NAIVE


def test_holdout_is_later_portion() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    times = [start + DAY * i for i in range(6)]
    result = evaluate_series(_series([10, 12, 14, 16, 18, 20], times), _eval(holdout=2))
    assert result.holdout_start == times[4]
    assert result.holdout_end == times[5]


def test_no_future_leakage_moving_average() -> None:
    result = evaluate_series(
        _series([10, 12, 14, 16, 18, 20]),
        _eval(model=ForecastModel.MOVING_AVERAGE, window=2, holdout=2),
    )
    assert result.training_observation_count == 4
    assert result.mae == 3.75


def test_positional_comparison_on_irregular_timestamps() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    times = [
        start,
        start + timedelta(hours=3),
        start + timedelta(days=2),
        start + timedelta(days=5),
    ]
    result = evaluate_series(_series([10, 12, 14, 16], times), _eval(holdout=2, interval=DAY))
    assert result.mae == 3.0
    assert result.holdout_start == times[2]
    assert result.holdout_end == times[3]


def test_evaluation_is_deterministic() -> None:
    series = _series([10, 12, 14, 16, 18, 20])
    request = _eval(holdout=2)
    assert evaluate_series(series, request) == evaluate_series(series, request)


def test_invalid_holdouts() -> None:
    series = _series([10, 12, 14])
    with pytest.raises(ForecastingValidationError, match="holdout"):
        evaluate_series(series, _eval(holdout=0))
    with pytest.raises(ForecastingValidationError, match="training"):
        evaluate_series(series, _eval(holdout=3))
    with pytest.raises(ForecastingValidationError, match="training"):
        evaluate_series(series, _eval(holdout=4))


def test_holdout_insufficient_for_moving_average_window() -> None:
    with pytest.raises(InsufficientHistoryError, match="window 3"):
        evaluate_series(
            _series([10, 12, 14, 16]),
            _eval(model=ForecastModel.MOVING_AVERAGE, window=3, holdout=2),
        )
