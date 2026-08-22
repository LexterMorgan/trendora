"""Deterministic in-memory baselines over M5 MetricSeries."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from trendora.analytics.models import MetricObservation, MetricSeries, ordered_observations
from trendora.analytics.repository import ObservationQuery, validate_observation_query
from trendora.analytics.service import AnalyticsService
from trendora.forecasting.exceptions import ForecastingValidationError, InsufficientHistoryError
from trendora.forecasting.models import (
    ComparisonRequest,
    ComparisonResult,
    EvaluationRequest,
    EvaluationResult,
    ForecastModel,
    ForecastPoint,
    ForecastRequest,
    ForecastResult,
)

_ORIGIN = "trendora_forecast"


class ForecastingService:
    """Fits baselines on M5 series. Does not query metric_snapshots or write."""

    def __init__(self, analytics: AnalyticsService) -> None:
        self._analytics = analytics

    def forecast(self, request: ForecastRequest) -> ForecastResult:
        _validate_forecast_request(request)
        series = self._analytics.get_metric_series(request.query)
        return forecast_series(series, request)

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        _validate_evaluation_request(request)
        series = self._analytics.get_metric_series(request.query)
        return evaluate_series(series, request)

    def compare(self, request: ComparisonRequest) -> ComparisonResult:
        _validate_comparison_request(request)
        series = self._analytics.get_metric_series(request.query)
        return compare_series(series, request)


def forecast_series(series: MetricSeries, request: ForecastRequest) -> ForecastResult:
    _validate_forecast_request(request)
    history = _ready_history(series, request.model, request.window)
    values = _predict_values(history, request.model, request.horizon, request.window, request.alpha)
    last = history[-1]
    points = tuple(
        ForecastPoint(at=_forecast_timestamp(last.observed_at, request.interval, step), value=value)
        for step, value in enumerate(values, start=1)
    )
    first = history[0]
    assert request.query.source_code is not None
    assert request.query.metric_name is not None
    return ForecastResult(
        source_code=request.query.source_code,
        metric_name=request.query.metric_name,
        model=request.model,
        interval=request.interval,
        horizon=request.horizon,
        origin=_ORIGIN,
        history_start=first.observed_at,
        history_end=last.observed_at,
        history_count=len(history),
        points=points,
        content_item_id=request.query.content_item_id,
        publisher_id=request.query.publisher_id,
    )


def evaluate_series(series: MetricSeries, request: EvaluationRequest) -> EvaluationResult:
    _validate_evaluation_request(request)
    ordered = _aware_ordered(series)
    train, test = _split_holdout(ordered, request.holdout)
    _require_model_history(train, request.model, request.window)
    train_request = ForecastRequest(
        query=request.query,
        model=request.model,
        horizon=len(test),
        interval=request.interval,
        window=request.window,
        alpha=request.alpha,
    )
    fitted = forecast_series(
        MetricSeries(
            observations=tuple(train),
            source_code=series.source_code,
            metric_name=series.metric_name,
        ),
        train_request,
    )
    actuals = [float(row.metric_value) for row in test]
    predicted = [point.value for point in fitted.points]
    mae = sum(abs(pred - actual) for pred, actual in zip(predicted, actuals, strict=True)) / len(actuals)
    return EvaluationResult(
        model=request.model,
        training_observation_count=len(train),
        test_observation_count=len(test),
        mae=mae,
        holdout_start=test[0].observed_at,
        holdout_end=test[-1].observed_at,
        origin=_ORIGIN,
    )


def compare_series(series: MetricSeries, request: ComparisonRequest) -> ComparisonResult:
    _validate_comparison_request(request)
    naive = evaluate_series(
        series,
        EvaluationRequest(
            query=request.query,
            model=ForecastModel.NAIVE,
            holdout=request.holdout,
            interval=request.interval,
        ),
    )
    challenger = evaluate_series(
        series,
        EvaluationRequest(
            query=request.query,
            model=request.challenger,
            holdout=request.holdout,
            interval=request.interval,
            window=request.window,
            alpha=request.alpha,
        ),
    )
    assert naive.training_observation_count == challenger.training_observation_count
    assert naive.test_observation_count == challenger.test_observation_count
    assert naive.holdout_start == challenger.holdout_start
    assert naive.holdout_end == challenger.holdout_end
    assert request.query.source_code is not None
    assert request.query.metric_name is not None
    return ComparisonResult(
        source_code=request.query.source_code,
        metric_name=request.query.metric_name,
        holdout=request.holdout,
        interval=request.interval,
        challenger=request.challenger,
        naive_mae=naive.mae,
        challenger_mae=challenger.mae,
        training_observation_count=naive.training_observation_count,
        test_observation_count=naive.test_observation_count,
        holdout_start=naive.holdout_start,
        holdout_end=naive.holdout_end,
        challenger_beats_naive=challenger.mae < naive.mae,
        origin=_ORIGIN,
        content_item_id=request.query.content_item_id,
        publisher_id=request.query.publisher_id,
    )


def _validate_forecast_request(request: ForecastRequest) -> None:
    _validate_identity(request.query)
    _validate_model_params(request.model, request.window, request.alpha)
    if request.horizon < 1:
        raise ForecastingValidationError("horizon must be a positive integer")
    _require_positive_interval(request.interval)


def _validate_evaluation_request(request: EvaluationRequest) -> None:
    _validate_identity(request.query)
    _validate_model_params(request.model, request.window, request.alpha)
    if request.holdout < 1:
        raise ForecastingValidationError("holdout must be a positive integer")
    _require_positive_interval(request.interval)


def _validate_comparison_request(request: ComparisonRequest) -> None:
    if request.challenger is ForecastModel.NAIVE:
        raise ForecastingValidationError(
            "challenger must be moving_average or simple_exponential_smoothing"
        )
    _validate_evaluation_request(
        EvaluationRequest(
            query=request.query,
            model=ForecastModel.NAIVE,
            holdout=request.holdout,
            interval=request.interval,
        )
    )
    _validate_evaluation_request(
        EvaluationRequest(
            query=request.query,
            model=request.challenger,
            holdout=request.holdout,
            interval=request.interval,
            window=request.window,
            alpha=request.alpha,
        )
    )


def _validate_identity(query: ObservationQuery) -> None:
    validate_observation_query(query)
    if not query.source_code:
        raise ForecastingValidationError("source_code is required")
    if not query.metric_name:
        raise ForecastingValidationError("metric_name is required")
    if query.content_item_id is None and query.publisher_id is None:
        raise ForecastingValidationError("content_item_id or publisher_id is required")


def _validate_model_params(model: ForecastModel, window: int | None, alpha: float | None) -> None:
    if model is ForecastModel.MOVING_AVERAGE:
        if window is None:
            raise ForecastingValidationError("moving_average requires window")
        if window < 1:
            raise ForecastingValidationError("window must be a positive integer")
        if alpha is not None:
            raise ForecastingValidationError("moving_average does not use alpha")
        return
    if model is ForecastModel.SIMPLE_EXPONENTIAL_SMOOTHING:
        if alpha is None:
            raise ForecastingValidationError("simple_exponential_smoothing requires alpha")
        if not 0 < alpha <= 1:
            raise ForecastingValidationError("alpha must satisfy 0 < alpha <= 1")
        if window is not None:
            raise ForecastingValidationError("simple_exponential_smoothing does not use window")
        return
    if window is not None:
        raise ForecastingValidationError("naive does not use window")
    if alpha is not None:
        raise ForecastingValidationError("naive does not use alpha")


def _require_positive_interval(interval: timedelta) -> None:
    if interval <= timedelta(0):
        raise ForecastingValidationError("interval must be a positive timedelta")


def _ready_history(
    series: MetricSeries,
    model: ForecastModel,
    window: int | None,
) -> tuple[MetricObservation, ...]:
    ordered = _aware_ordered(series)
    _require_model_history(ordered, model, window)
    return ordered


def _aware_ordered(series: MetricSeries) -> tuple[MetricObservation, ...]:
    ordered = ordered_observations(series.observations)
    if not ordered:
        raise InsufficientHistoryError("forecasting requires at least one observation")
    for row in ordered:
        if row.observed_at.tzinfo is None or row.collected_at.tzinfo is None:
            raise ForecastingValidationError("observation timestamps must be timezone-aware")
    return ordered


def _require_model_history(
    history: Sequence[MetricObservation],
    model: ForecastModel,
    window: int | None,
) -> None:
    if not history:
        raise InsufficientHistoryError("forecasting requires at least one observation")
    if model is ForecastModel.MOVING_AVERAGE:
        assert window is not None
        if len(history) < window:
            raise InsufficientHistoryError(
                f"moving_average window {window} exceeds history of {len(history)}"
            )


def _split_holdout(
    history: Sequence[MetricObservation],
    holdout: int,
) -> tuple[tuple[MetricObservation, ...], tuple[MetricObservation, ...]]:
    if holdout >= len(history):
        raise ForecastingValidationError("holdout must leave a non-empty training set")
    train = tuple(history[:-holdout])
    test = tuple(history[-holdout:])
    if not train:
        raise ForecastingValidationError("training set is empty")
    if not test:
        raise ForecastingValidationError("test set is empty")
    return train, test


def _predict_values(
    history: Sequence[MetricObservation],
    model: ForecastModel,
    horizon: int,
    window: int | None,
    alpha: float | None,
) -> list[float]:
    values = [float(row.metric_value) for row in history]
    if model is ForecastModel.NAIVE:
        latest = values[-1]
        return [latest] * horizon
    if model is ForecastModel.MOVING_AVERAGE:
        assert window is not None
        rolling = list(values)
        out: list[float] = []
        for _ in range(horizon):
            nxt = sum(rolling[-window:]) / window
            out.append(nxt)
            rolling.append(nxt)
        return out
    assert alpha is not None
    level = values[0]
    for value in values[1:]:
        level = alpha * value + (1.0 - alpha) * level
    return [level] * horizon


def _forecast_timestamp(latest: datetime, interval: timedelta, step: int) -> datetime:
    return latest + interval * step
