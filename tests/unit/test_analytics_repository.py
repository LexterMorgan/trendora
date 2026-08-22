"""In-memory analytics repository filter/order tests. No database."""

from datetime import datetime

import pytest

from trendora.analytics.exceptions import AnalyticsQueryError
from trendora.analytics.repository import (
    InMemoryAnalyticsRepository,
    ObservationQuery,
    apply_observation_query,
)
from trendora.reference import MARKET_IDS
from tests.fixtures.analytics_observations import (
    GOLDEN_OBSERVATIONS,
    HN_STORY_ID,
    SNAP_HN_SCORE_T12_A,
    SNAP_HN_SCORE_T12_B,
    T10,
    T12,
    T15,
    YT_CHANNEL_ID,
    YT_VIDEO_ID,
)

REPO = InMemoryAnalyticsRepository(GOLDEN_OBSERVATIONS)


def test_empty_query_result_is_empty_not_fabricated() -> None:
    rows = REPO.list_observations(ObservationQuery(metric_name="does_not_exist"))
    assert rows == []


def test_source_and_metric_filters() -> None:
    rows = REPO.list_observations(
        ObservationQuery(source_code="github", metric_name="stargazer_count")
    )
    assert [row.metric_value for row in rows] == [11]
    assert rows[0].source_code == "github"
    assert rows[0].market_id is None


def test_content_and_publisher_subjects_are_distinct() -> None:
    content = REPO.list_observations(ObservationQuery(content_item_id=YT_VIDEO_ID, metric_name="view_count"))
    publisher = REPO.list_observations(
        ObservationQuery(publisher_id=YT_CHANNEL_ID, metric_name="subscriber_count")
    )
    assert [row.metric_value for row in content] == [100, 150, 200]
    assert [row.metric_value for row in publisher] == [50, 60]
    assert all(row.subject_kind.value == "content_item" for row in content)
    assert all(row.subject_kind.value == "publisher" for row in publisher)


def test_publisher_filter_does_not_return_content_metrics() -> None:
    rows = REPO.list_observations(ObservationQuery(publisher_id=YT_CHANNEL_ID, metric_name="view_count"))
    assert rows == []


def test_nullable_market_is_preserved() -> None:
    rows = REPO.list_observations(ObservationQuery(content_item_id=HN_STORY_ID, metric_name="score"))
    assert rows
    assert all(row.market_id is None for row in rows)
    assert all(row.publisher_id is None for row in rows)


def test_market_filter_uses_existing_relationship() -> None:
    id_rows = REPO.list_observations(
        ObservationQuery(source_code="youtube", metric_name="view_count", market_id=MARKET_IDS["ID"])
    )
    sg_rows = REPO.list_observations(
        ObservationQuery(source_code="youtube", metric_name="view_count", market_id=MARKET_IDS["SG"])
    )
    assert [row.metric_value for row in id_rows] == [100, 150, 200]
    assert sg_rows == []


def test_time_window_is_start_inclusive_end_exclusive() -> None:
    rows = REPO.list_observations(
        ObservationQuery(
            content_item_id=YT_VIDEO_ID,
            metric_name="view_count",
            observed_from=T12,
            observed_until=T15,
        )
    )
    assert [row.observed_at for row in rows] == [T12]
    assert [row.metric_value for row in rows] == [150]


def test_naive_time_bounds_are_rejected() -> None:
    naive = datetime(2026, 8, 21, 12, 0)
    with pytest.raises(AnalyticsQueryError, match="timezone-aware"):
        apply_observation_query(GOLDEN_OBSERVATIONS, ObservationQuery(observed_from=naive))
    with pytest.raises(AnalyticsQueryError, match="timezone-aware"):
        REPO.list_observations(ObservationQuery(observed_until=naive))


def test_content_and_publisher_filters_are_mutually_exclusive() -> None:
    with pytest.raises(AnalyticsQueryError, match="mutually exclusive"):
        REPO.list_observations(
            ObservationQuery(content_item_id=YT_VIDEO_ID, publisher_id=YT_CHANNEL_ID)
        )


def test_duplicate_observed_at_uses_collected_at_then_id() -> None:
    rows = REPO.list_observations(ObservationQuery(content_item_id=HN_STORY_ID, metric_name="score"))
    assert [row.snapshot_id for row in rows] == [SNAP_HN_SCORE_T12_A, SNAP_HN_SCORE_T12_B]
    assert [row.metric_value for row in rows] == [10, 12]
    latest = REPO.get_latest_observation(ObservationQuery(content_item_id=HN_STORY_ID, metric_name="score"))
    assert latest is not None
    assert latest.snapshot_id == SNAP_HN_SCORE_T12_B
    assert latest.metric_value == 12


def test_missing_like_count_is_not_filled() -> None:
    rows = REPO.list_observations(ObservationQuery(content_item_id=YT_VIDEO_ID, metric_name="like_count"))
    assert [row.observed_at for row in rows] == [T10, T15]
    assert [row.metric_value for row in rows] == [1, 3]


def test_same_query_is_deterministic() -> None:
    query = ObservationQuery(source_code="youtube", metric_name="view_count")
    assert REPO.list_observations(query) == REPO.list_observations(query)


def test_in_memory_repository_has_no_sql_escape_hatch() -> None:
    assert not hasattr(REPO, "execute_sql")
    assert not hasattr(REPO, "execute")
