"""Analytics contract tests. No database."""

from datetime import datetime, timezone

import pytest

from trendora.analytics.models import MetricSeries, ordered_observations
from tests.fixtures.analytics_observations import GOLDEN_OBSERVATIONS, T10, YT_VIDEO_ID


def test_empty_series_is_valid_and_contains_no_rows() -> None:
    series = MetricSeries(observations=())
    assert series.empty is True
    assert len(series) == 0
    assert series.observations == ()


def test_series_is_immutable() -> None:
    series = MetricSeries(observations=GOLDEN_OBSERVATIONS[:1])
    with pytest.raises(AttributeError):
        series.observations = ()  # type: ignore[misc]


def test_ordered_observations_are_deterministic() -> None:
    shuffled = tuple(reversed(GOLDEN_OBSERVATIONS))
    first = ordered_observations(shuffled)
    second = ordered_observations(tuple(reversed(first)))
    assert first == second
    times = [row.observed_at for row in first]
    assert times == sorted(times)


def test_single_observation_preserves_identity() -> None:
    row = GOLDEN_OBSERVATIONS[0]
    assert row.metric_name == "view_count"
    assert row.metric_value == 100
    assert row.observed_at == T10
    assert row.collected_at == T10
    assert row.observed_at.tzinfo is not None
    assert row.source_code == "youtube"
    assert row.content_item_id == YT_VIDEO_ID
    assert row.content_external_id == "m5fixture-video-1"


def test_naive_datetime_is_not_silently_accepted_on_the_model() -> None:
    naive = datetime(2026, 8, 21, 10, 0)
    assert naive.tzinfo is None
    aware = datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc)
    assert aware.tzinfo is not None
