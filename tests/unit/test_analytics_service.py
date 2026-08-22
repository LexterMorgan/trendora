"""Analytics service tests using the golden in-memory fixture. No database."""

import pytest

from trendora.analytics.exceptions import AnalyticsAggregationError
from trendora.analytics.models import Aggregation
from trendora.analytics.repository import InMemoryAnalyticsRepository, ObservationQuery
from trendora.analytics.service import AnalyticsService
from tests.fixtures.analytics_observations import (
    GOLDEN_OBSERVATIONS,
    GH_REPO_ID,
    HN_STORY_ID,
    SE_QUESTION_ID,
    T10,
    T15,
    YT_CHANNEL_ID,
    YT_VIDEO_ID,
)


def _service() -> AnalyticsService:
    return AnalyticsService(InMemoryAnalyticsRepository(GOLDEN_OBSERVATIONS))


def test_empty_series() -> None:
    series = _service().get_metric_series(ObservationQuery(metric_name="nope"))
    assert series.empty
    assert series.observations == ()


def test_multi_source_golden_fixture_contracts() -> None:
    service = _service()
    yt = service.get_content_metric_series(YT_VIDEO_ID, "view_count")
    assert [row.metric_value for row in yt.observations] == [100, 150, 200]
    hn = service.get_content_metric_series(HN_STORY_ID, "comment_count")
    assert [row.metric_value for row in hn.observations] == [4]
    se = service.get_content_metric_series(SE_QUESTION_ID, "answer_count")
    assert [row.metric_value for row in se.observations] == [2]
    gh = service.get_content_metric_series(GH_REPO_ID, "fork_count")
    assert [row.metric_value for row in gh.observations] == [3]
    assert gh.observations[0].source_code == "github"
    assert se.observations[0].market_id is None
    assert hn.observations[0].publisher_id is None


def test_publisher_series() -> None:
    series = _service().get_publisher_metric_series(YT_CHANNEL_ID, "subscriber_count")
    assert [row.metric_value for row in series.observations] == [50, 60]
    assert all(row.subject_kind.value == "publisher" for row in series.observations)


def test_latest_observation() -> None:
    latest = _service().get_latest_observation(
        ObservationQuery(content_item_id=YT_VIDEO_ID, metric_name="view_count")
    )
    assert latest is not None
    assert latest.metric_value == 200
    assert latest.observed_at == T15


def test_count_and_timestamp_aggregates() -> None:
    service = _service()
    query = ObservationQuery(content_item_id=YT_VIDEO_ID, metric_name="view_count")
    count = service.summarize(query, aggregation=Aggregation.COUNT)
    assert count.origin == "trendora_derived"
    assert count.value == 3
    assert count.observation_count == 3
    assert count.earliest_observed_at == T10
    assert count.latest_observed_at == T15
    earliest = service.summarize(query, aggregation="earliest_observed_at")
    assert earliest.value == T10
    latest = service.summarize(query, aggregation=Aggregation.LATEST_OBSERVED_AT)
    assert latest.value == T15


def test_latest_value_requires_subject_and_metric() -> None:
    service = _service()
    with pytest.raises(AnalyticsAggregationError, match="metric_name"):
        service.summarize(ObservationQuery(content_item_id=YT_VIDEO_ID), aggregation="latest_value")
    with pytest.raises(AnalyticsAggregationError, match="content_item_id or publisher_id"):
        service.summarize(ObservationQuery(metric_name="view_count"), aggregation="latest_value")
    summary = service.summarize(
        ObservationQuery(content_item_id=YT_VIDEO_ID, metric_name="view_count"),
        aggregation=Aggregation.LATEST_VALUE,
    )
    assert summary.value == 200
    assert summary.origin == "trendora_derived"


def test_unsupported_aggregations_are_rejected() -> None:
    service = _service()
    query = ObservationQuery(content_item_id=YT_VIDEO_ID, metric_name="view_count")
    for name in ("sum", "mean", "engagement_rate", "trendora_score"):
        with pytest.raises(AnalyticsAggregationError, match="Unsupported"):
            service.summarize(query, aggregation=name)


def test_empty_latest_value_is_none_not_zero() -> None:
    summary = _service().summarize(
        ObservationQuery(content_item_id=YT_VIDEO_ID, metric_name="missing"),
        aggregation=Aggregation.LATEST_VALUE,
    )
    assert summary.value is None
    assert summary.observation_count == 0


def test_service_does_not_expose_sql_or_api_clients() -> None:
    service = _service()
    assert not hasattr(service, "execute_sql")
    assert not hasattr(service, "youtube")
    assert not hasattr(service, "http")
