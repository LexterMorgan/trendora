"""V1 GitHub forecast product tests. No database, no source APIs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from trendora.analytics.models import MetricObservation, MetricSeries, SubjectKind
from trendora.analytics.repository import InMemoryAnalyticsRepository, ObservationQuery
from trendora.analytics.service import AnalyticsService
from trendora.diagnostics.models import CadenceClass
from trendora.forecasting import (
    ForecastModel,
    ForecastRequest,
    ForecastingValidationError,
    InsufficientHistoryError,
)
from trendora.forecasting.service import forecast_series
from trendora.product import (
    V1_HORIZON,
    V1_INTERVAL,
    V1_METRICS,
    V1_MIN_OBSERVATIONS,
    V1_ORIGIN,
    V1_SOURCE,
    GitHubForecastProduct,
    GitHubForecastRequest,
)
from trendora.reference import SOURCE_IDS

UTC = timezone.utc
REPO = UUID("88888888-8888-4888-8888-888888888801")
REPO_EXT = "m10fixture/repo"
T0 = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
DAY = timedelta(days=1)
WEEK = timedelta(days=7)


def _obs(value: int, at: datetime, snapshot: int, *, metric: str = "stargazer_count") -> MetricObservation:
    return MetricObservation(
        snapshot_id=UUID(int=snapshot),
        source_code="github",
        source_id=SOURCE_IDS["github"],
        metric_name=metric,
        metric_value=value,
        observed_at=at,
        collected_at=at,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=REPO,
        content_external_id=REPO_EXT,
        content_type="repository",
    )


def _rows(*pairs: tuple[int, datetime], metric: str = "stargazer_count") -> tuple[MetricObservation, ...]:
    return tuple(_obs(value, at, i + 1, metric=metric) for i, (value, at) in enumerate(pairs))


def _product(*observations: MetricObservation) -> GitHubForecastProduct:
    repository = InMemoryAnalyticsRepository(observations)
    return GitHubForecastProduct(AnalyticsService(repository))


def _regular_stars() -> tuple[MetricObservation, ...]:
    return _rows((10, T0), (12, T0 + DAY), (15, T0 + 2 * DAY), (20, T0 + 3 * DAY))


def test_stargazer_forecast_succeeds_with_four_observations() -> None:
    result = _product(*_regular_stars()).forecast(
        GitHubForecastRequest(content_item_id=REPO, metric_name="stargazer_count")
    )
    assert result.metric_name == "stargazer_count"
    assert result.source_code == "github"
    assert result.content_item_id == REPO
    assert result.content_external_id == REPO_EXT


def test_stargazer_forecast_succeeds_with_more_than_four_observations() -> None:
    rows = _rows(
        (5, T0),
        (8, T0 + DAY),
        (10, T0 + 2 * DAY),
        (12, T0 + 3 * DAY),
        (20, T0 + 4 * DAY),
    )
    result = _product(*rows).forecast(
        GitHubForecastRequest(content_item_id=REPO, metric_name="stargazer_count")
    )
    assert result.observation_count == 5


def test_fork_forecast_succeeds() -> None:
    rows = _rows(
        (1, T0),
        (2, T0 + DAY),
        (2, T0 + 2 * DAY),
        (3, T0 + 3 * DAY),
        metric="fork_count",
    )
    result = _product(*rows).forecast(
        GitHubForecastRequest(content_item_id=REPO, metric_name="fork_count")
    )
    assert result.metric_name == "fork_count"
    assert result.observation_count == 4


def test_exactly_four_forecast_points() -> None:
    result = _product(*_regular_stars()).forecast(
        GitHubForecastRequest(content_item_id=REPO, metric_name="stargazer_count")
    )
    assert len(result.points) == 4
    assert result.horizon == 4


def test_model_is_naive() -> None:
    result = _product(*_regular_stars()).forecast(
        GitHubForecastRequest(content_item_id=REPO, metric_name="stargazer_count")
    )
    assert result.model is ForecastModel.NAIVE


def test_interval_is_exactly_seven_days() -> None:
    result = _product(*_regular_stars()).forecast(
        GitHubForecastRequest(content_item_id=REPO, metric_name="stargazer_count")
    )
    assert result.interval == timedelta(days=7)
    assert result.interval == V1_INTERVAL


def test_forecast_timestamps_are_latest_plus_7_14_21_28_days() -> None:
    result = _product(*_regular_stars()).forecast(
        GitHubForecastRequest(content_item_id=REPO, metric_name="stargazer_count")
    )
    latest = T0 + 3 * DAY
    assert [point.at for point in result.points] == [
        latest + WEEK,
        latest + 2 * WEEK,
        latest + 3 * WEEK,
        latest + 4 * WEEK,
    ]


def test_forecast_values_match_naive_level() -> None:
    result = _product(*_regular_stars()).forecast(
        GitHubForecastRequest(content_item_id=REPO, metric_name="stargazer_count")
    )
    assert [point.value for point in result.points] == [20.0, 20.0, 20.0, 20.0]


def test_four_observations_is_enough() -> None:
    result = _product(*_regular_stars()).forecast(
        GitHubForecastRequest(content_item_id=REPO, metric_name="stargazer_count")
    )
    assert result.observation_count == 4


def test_three_observations_fails_as_insufficient_history() -> None:
    rows = _rows((10, T0), (12, T0 + DAY), (15, T0 + 2 * DAY))
    with pytest.raises(InsufficientHistoryError):
        _product(*rows).forecast(
            GitHubForecastRequest(content_item_id=REPO, metric_name="stargazer_count")
        )


def test_empty_history_fails_as_insufficient_history() -> None:
    with pytest.raises(InsufficientHistoryError):
        _product().forecast(
            GitHubForecastRequest(content_item_id=REPO, metric_name="stargazer_count")
        )


def test_unsupported_source_fails() -> None:
    with pytest.raises(ForecastingValidationError):
        _product(*_regular_stars()).forecast(
            GitHubForecastRequest(
                content_item_id=REPO,
                metric_name="stargazer_count",
                source_code="youtube",
            )
        )


def test_arbitrary_source_code_fails() -> None:
    with pytest.raises(ForecastingValidationError):
        _product(*_regular_stars()).forecast(
            GitHubForecastRequest(
                content_item_id=REPO,
                metric_name="stargazer_count",
                source_code="not-a-source",
            )
        )


def test_unsupported_metric_fails() -> None:
    with pytest.raises(ForecastingValidationError):
        _product(*_regular_stars()).forecast(
            GitHubForecastRequest(content_item_id=REPO, metric_name="view_count")
        )


def test_publisher_subject_fails() -> None:
    publisher = UUID("88888888-8888-4888-8888-888888888802")
    with pytest.raises(ForecastingValidationError):
        _product(*_regular_stars()).forecast(
            GitHubForecastRequest(
                content_item_id=REPO,
                publisher_id=publisher,
                metric_name="stargazer_count",
            )
        )


def test_missing_content_item_id_fails() -> None:
    with pytest.raises(ForecastingValidationError):
        _product(*_regular_stars()).forecast(
            GitHubForecastRequest(metric_name="stargazer_count")
        )


def test_provenance_origin_is_trendora_forecast() -> None:
    result = _product(*_regular_stars()).forecast(
        GitHubForecastRequest(content_item_id=REPO, metric_name="stargazer_count")
    )
    assert result.origin == "trendora_forecast"
    assert result.origin == V1_ORIGIN


def test_historical_series_is_not_mutated() -> None:
    rows = list(_regular_stars())
    before = [(o.metric_value, o.observed_at, o.snapshot_id) for o in rows]
    _product(*rows).forecast(
        GitHubForecastRequest(content_item_id=REPO, metric_name="stargazer_count")
    )
    after = [(o.metric_value, o.observed_at, o.snapshot_id) for o in rows]
    assert after == before
    assert len(rows) == 4


def test_irregular_timestamps_do_not_cause_resampling() -> None:
    rows = _rows((10, T0), (12, T0 + DAY), (15, T0 + 5 * DAY), (20, T0 + 9 * DAY))
    result = _product(*rows).forecast(
        GitHubForecastRequest(content_item_id=REPO, metric_name="stargazer_count")
    )
    assert result.observation_count == 4
    assert len(result.points) == 4
    latest = T0 + 9 * DAY
    assert [point.at for point in result.points] == [
        latest + WEEK,
        latest + 2 * WEEK,
        latest + 3 * WEEK,
        latest + 4 * WEEK,
    ]
    assert [point.value for point in result.points] == [20.0, 20.0, 20.0, 20.0]


def test_irregular_cadence_is_a_factual_caveat_not_a_rejection() -> None:
    irregular = _rows((10, T0), (12, T0 + DAY), (15, T0 + 5 * DAY), (20, T0 + 9 * DAY))
    result = _product(*irregular).forecast(
        GitHubForecastRequest(content_item_id=REPO, metric_name="stargazer_count")
    )
    assert result.cadence is CadenceClass.VARIABLE
    assert result.irregular_cadence is True
    assert len(result.points) == 4


def test_constant_cadence_is_not_marked_irregular() -> None:
    result = _product(*_regular_stars()).forecast(
        GitHubForecastRequest(content_item_id=REPO, metric_name="stargazer_count")
    )
    assert result.cadence is CadenceClass.EFFECTIVELY_CONSTANT
    assert result.irregular_cadence is False


def test_result_exposes_history_and_freshness_context() -> None:
    result = _product(*_regular_stars()).forecast(
        GitHubForecastRequest(content_item_id=REPO, metric_name="stargazer_count")
    )
    assert result.observation_count == 4
    assert result.history_start == T0
    assert result.history_end == T0 + 3 * DAY
    assert result.latest_observed_at == T0 + 3 * DAY


def test_result_matches_existing_m6a_naive_forecast() -> None:
    rows = _regular_stars()
    product_result = _product(*rows).forecast(
        GitHubForecastRequest(content_item_id=REPO, metric_name="stargazer_count")
    )
    series = MetricSeries(
        observations=rows,
        source_code="github",
        metric_name="stargazer_count",
    )
    m6a = forecast_series(
        series,
        ForecastRequest(
            query=ObservationQuery(
                source_code="github",
                metric_name="stargazer_count",
                content_item_id=REPO,
            ),
            model=ForecastModel.NAIVE,
            horizon=V1_HORIZON,
            interval=V1_INTERVAL,
        ),
    )
    assert product_result.points == m6a.points
    assert product_result.origin == m6a.origin
    assert product_result.observation_count == m6a.history_count


def test_v1_constants_are_stable() -> None:
    assert V1_SOURCE == "github"
    assert V1_METRICS == frozenset({"stargazer_count", "fork_count"})
    assert V1_HORIZON == 4
    assert V1_INTERVAL == timedelta(days=7)
    assert V1_MIN_OBSERVATIONS == 4
    assert V1_ORIGIN == "trendora_forecast"
