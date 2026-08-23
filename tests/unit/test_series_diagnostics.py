"""M7 series diagnostics. No database. No forecast models."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import stdev
from uuid import UUID

import pytest

from trendora.analytics.models import MetricObservation, MetricSeries, SubjectKind
from trendora.analytics.repository import InMemoryAnalyticsRepository, ObservationQuery
from trendora.analytics.service import AnalyticsService
from trendora.diagnostics import (
    CadenceClass,
    DiagnosticsService,
    DiagnosticsValidationError,
    MonotonicityClass,
    diagnose_series,
)
from trendora.reference import SOURCE_IDS
from tests.fixtures.analytics_observations import GOLDEN_OBSERVATIONS, YT_VIDEO_ID

UTC = timezone.utc
SUBJECT = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


def _obs(
    value: int,
    at: datetime,
    snapshot: int,
    *,
    collected_at: datetime | None = None,
    source_code: str = "github",
    metric_name: str = "stargazer_count",
    content_item_id: UUID | None = SUBJECT,
) -> MetricObservation:
    collected = collected_at if collected_at is not None else at
    return MetricObservation(
        snapshot_id=UUID(int=snapshot),
        source_code=source_code,
        source_id=SOURCE_IDS[source_code],
        metric_name=metric_name,
        metric_value=value,
        observed_at=at,
        collected_at=collected,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=content_item_id,
        content_type="repository",
    )


def _series(
    values: list[int],
    times: list[datetime] | None = None,
    *,
    source_code: str = "github",
    metric_name: str = "stargazer_count",
    collected_at: list[datetime] | None = None,
) -> MetricSeries:
    if times is None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        times = [start + DAY * i for i in range(len(values))]
    rows = []
    for i, (value, at) in enumerate(zip(values, times, strict=True)):
        collected = collected_at[i] if collected_at is not None else at
        rows.append(
            _obs(
                value,
                at,
                i + 1,
                collected_at=collected,
                source_code=source_code,
                metric_name=metric_name,
            )
        )
    return MetricSeries(
        observations=tuple(rows),
        source_code=source_code,
        metric_name=metric_name,
    )


def test_empty_series() -> None:
    result = diagnose_series(
        MetricSeries(observations=(), source_code="youtube", metric_name="view_count")
    )
    assert result.observation_count == 0
    assert result.first_observed_at is None
    assert result.last_observed_at is None
    assert result.elapsed_duration is None
    assert result.gap_count == 0
    assert result.min_gap is None
    assert result.mean_delta is None
    assert result.monotonicity is MonotonicityClass.NO_DELTA_DATA
    assert result.cadence is CadenceClass.NO_GAP_DATA
    assert result.source_code == "youtube"
    assert result.metric_name == "view_count"
    assert result.content_item_id is None
    assert result.origin == "trendora_diagnostic"


def test_one_observation() -> None:
    start = datetime(2026, 3, 1, tzinfo=UTC)
    result = diagnose_series(_series([42], [start]))
    assert result.observation_count == 1
    assert result.first_observed_at == start
    assert result.last_observed_at == start
    assert result.elapsed_duration == timedelta(0)
    assert result.gap_count == 0
    assert result.delta_count == 0
    assert result.positive_delta_count == 0
    assert result.min_delta is None
    assert result.monotonicity is MonotonicityClass.NO_DELTA_DATA
    assert result.cadence is CadenceClass.NO_GAP_DATA
    assert result.content_item_id == SUBJECT


def test_regular_timestamps_and_gap_statistics() -> None:
    result = diagnose_series(_series([10, 20, 30, 40]))
    assert result.gap_count == 3
    assert result.min_gap == DAY
    assert result.max_gap == DAY
    assert result.mean_gap == DAY
    assert result.median_gap == DAY
    assert result.zero_gap_count == 0
    assert result.unique_gap_count == 1
    assert result.gaps_differing_from_median_count == 0
    assert result.gap_coefficient_of_variation == 0.0
    assert result.cadence is CadenceClass.EFFECTIVELY_CONSTANT


def test_irregular_timestamps() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    times = [start, start + HOUR, start + DAY, start + DAY * 4]
    result = diagnose_series(_series([1, 2, 3, 4], times))
    gaps = [HOUR, DAY - HOUR, DAY * 3]
    assert result.min_gap == HOUR
    assert result.max_gap == DAY * 3
    assert result.mean_gap == sum(gaps, timedelta(0)) / 3
    assert result.median_gap == DAY - HOUR
    assert result.unique_gap_count == 3
    assert result.gaps_differing_from_median_count == 2
    assert result.cadence is CadenceClass.VARIABLE
    assert result.gap_coefficient_of_variation is not None
    assert result.gap_coefficient_of_variation > 0


def test_zero_gaps_and_duplicate_observed_at() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    times = [start, start, start + DAY]
    collected = [start, start + HOUR, start + DAY]
    result = diagnose_series(_series([10, 11, 12], times, collected_at=collected))
    assert result.zero_gap_count == 1
    assert result.min_gap == timedelta(0)
    assert result.duplicate_observed_at_group_count == 1
    assert result.duplicate_observed_at_observation_count == 2
    assert result.duplicate_observed_at_conflicting_value_group_count == 1
    assert result.duplicate_observed_at_groups_resolved_by_collected_at == 1
    assert result.duplicate_observed_at_groups_with_tied_collected_at == 0


def test_duplicate_observed_at_tied_collected_at() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    times = [start, start]
    collected = [start, start]
    result = diagnose_series(_series([5, 5], times, collected_at=collected))
    assert result.duplicate_observed_at_group_count == 1
    assert result.duplicate_observed_at_conflicting_value_group_count == 0
    assert result.duplicate_observed_at_groups_resolved_by_collected_at == 0
    assert result.duplicate_observed_at_groups_with_tied_collected_at == 1


def test_monotonic_increasing() -> None:
    result = diagnose_series(_series([10, 12, 15, 15, 20]))
    assert result.monotonicity is MonotonicityClass.NON_DECREASING
    assert result.positive_delta_count == 3
    assert result.zero_delta_count == 1
    assert result.negative_delta_count == 0
    assert result.fraction_decreasing == 0.0
    assert result.total_positive_movement == 10
    assert result.total_negative_movement == 0


def test_monotonic_decreasing() -> None:
    result = diagnose_series(_series([20, 18, 15, 10]))
    assert result.monotonicity is MonotonicityClass.NON_INCREASING
    assert result.negative_delta_count == 3
    assert result.positive_delta_count == 0
    assert result.min_delta == -5
    assert result.max_delta == -2
    assert result.total_negative_movement == 10


def test_constant_and_all_zero_changes() -> None:
    result = diagnose_series(_series([7, 7, 7, 7]))
    assert result.monotonicity is MonotonicityClass.CONSTANT
    assert result.zero_delta_count == 3
    assert result.positive_delta_count == 0
    assert result.negative_delta_count == 0
    assert result.min_delta == 0
    assert result.max_delta == 0
    assert result.mean_delta == 0.0
    assert result.mean_absolute_delta == 0.0
    assert result.fraction_flat == 1.0


def test_mixed_positive_and_negative_changes() -> None:
    result = diagnose_series(_series([10, 20, 15, 18]))
    assert result.monotonicity is MonotonicityClass.MIXED
    assert result.positive_delta_count == 2
    assert result.negative_delta_count == 1
    assert result.zero_delta_count == 0
    assert result.min_delta == -5
    assert result.max_delta == 10
    assert result.mean_delta == 8 / 3
    assert result.mean_absolute_delta == 6.0
    assert result.max_absolute_delta == 10
    assert result.stdev_delta == pytest.approx(stdev([10, -5, 3]))
    assert result.total_positive_movement == 13
    assert result.total_negative_movement == 5
    assert result.fraction_non_decreasing == 2 / 3
    assert result.fraction_decreasing == 1 / 3


def test_cumulative_looking_with_and_without_decreases() -> None:
    clean = diagnose_series(_series([100, 150, 200, 250]))
    assert clean.negative_delta_count == 0
    assert clean.fraction_non_decreasing == 1.0
    assert clean.monotonicity is MonotonicityClass.NON_DECREASING
    noisy = diagnose_series(_series([100, 150, 140, 180]))
    assert noisy.negative_delta_count == 1
    assert noisy.fraction_decreasing == pytest.approx(1 / 3)
    assert noisy.monotonicity is MonotonicityClass.MIXED
    assert not hasattr(clean, "forecastable")
    assert not hasattr(clean, "recommended_model")


def test_m5_does_not_carry_null_metric_values() -> None:
    result = diagnose_series(_series([0, 0, 4]))
    assert result.observation_count == 3
    assert result.zero_delta_count == 1
    assert result.positive_delta_count == 1
    assert all(row.metric_value is not None for row in _series([0, 0, 4]).observations)


def test_identity_preserved_and_timezone_aware() -> None:
    start = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    result = diagnose_series(
        _series(
            [1, 2],
            [start, start + DAY],
            source_code="youtube",
            metric_name="view_count",
        )
    )
    assert result.source_code == "youtube"
    assert result.metric_name == "view_count"
    assert result.content_item_id == SUBJECT
    assert result.publisher_id is None
    assert result.first_observed_at.tzinfo is not None
    assert result.last_observed_at.tzinfo is not None
    assert result.elapsed_duration == DAY


def test_naive_datetime_rejected() -> None:
    naive = datetime(2026, 1, 1)
    with pytest.raises(DiagnosticsValidationError, match="timezone-aware"):
        diagnose_series(_series([1, 2], [naive, naive + DAY]))


def test_deterministic_and_does_not_mutate_input() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    later = start + DAY
    unordered = MetricSeries(
        observations=(
            _obs(20, later, 2),
            _obs(10, start, 1),
        ),
        source_code="github",
        metric_name="stargazer_count",
    )
    before = unordered.observations
    first = diagnose_series(unordered)
    second = diagnose_series(unordered)
    assert first == second
    assert unordered.observations is before
    assert unordered.observations[0].metric_value == 20
    assert first.first_observed_at == start
    assert first.last_observed_at == later
    assert first.min_delta == 10


def test_service_diagnose_uses_m5_series() -> None:
    service = DiagnosticsService(AnalyticsService(InMemoryAnalyticsRepository(GOLDEN_OBSERVATIONS)))
    result = service.diagnose(
        ObservationQuery(
            source_code="youtube",
            metric_name="view_count",
            content_item_id=YT_VIDEO_ID,
        )
    )
    assert result.source_code == "youtube"
    assert result.metric_name == "view_count"
    assert result.content_item_id == YT_VIDEO_ID
    assert result.observation_count == 3
    assert result.monotonicity is MonotonicityClass.NON_DECREASING
    assert result.cadence is CadenceClass.VARIABLE
    assert result.min_delta == 50
    assert result.max_delta == 50
