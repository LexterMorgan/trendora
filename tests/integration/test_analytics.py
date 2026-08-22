"""PostgreSQL analytics read tests.

These tests roll back and never call source APIs. Assertions are scoped to
M5 fixture identities.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from trendora.analytics.models import Aggregation
from trendora.analytics.repository import ObservationQuery
from trendora.analytics.service import AnalyticsService
from trendora.config import reset_settings_cache
from trendora.db.session import get_engine, reset_engine
from trendora.models import MetricSnapshot
from trendora.reference import MARKET_IDS
from tests.fixtures.analytics_observations import (
    GH_REPO_ID,
    HN_STORY_ID,
    SE_QUESTION_ID,
    SNAP_HN_SCORE_T12_B,
    SNAP_YT_VIEW_T12,
    T12,
    T15,
    YT_CHANNEL_ID,
    YT_VIDEO_ID,
    seed_analytics_fixture,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def db_session(database_url: str) -> Session:
    assert database_url
    reset_settings_cache()
    reset_engine()
    engine = get_engine()
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        seed_analytics_fixture(session)
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        reset_engine()
        reset_settings_cache()


def test_sql_series_matches_fixture_identities(db_session: Session) -> None:
    service = AnalyticsService.from_session(db_session)
    views = service.get_content_metric_series(YT_VIDEO_ID, "view_count")
    assert [row.metric_value for row in views.observations] == [100, 150, 200]
    assert views.observations[0].source_code == "youtube"
    assert views.observations[0].publisher_external_id == "UCm5fixture000000000000001"
    assert views.observations[0].market_code == "ID"

    hn = service.get_content_metric_series(HN_STORY_ID, "score")
    assert hn.observations[0].market_id is None
    assert hn.observations[0].publisher_id is None
    assert [row.metric_value for row in hn.observations] == [10, 12]

    se = service.get_content_metric_series(SE_QUESTION_ID, "view_count")
    assert se.observations[0].source_code == "stack_exchange"
    assert se.observations[0].market_id is None

    gh = service.get_content_metric_series(GH_REPO_ID, "stargazer_count")
    assert gh.observations[0].content_type == "repository"
    assert gh.observations[0].market_id is None


def test_sql_time_filter_and_latest(db_session: Session) -> None:
    service = AnalyticsService.from_session(db_session)
    window = service.get_content_metric_series(
        YT_VIDEO_ID,
        "view_count",
        observed_from=T12,
        observed_until=T15,
    )
    assert [row.snapshot_id for row in window.observations] == [SNAP_YT_VIEW_T12]
    latest = service.get_latest_observation(
        ObservationQuery(content_item_id=HN_STORY_ID, metric_name="score")
    )
    assert latest is not None
    assert latest.snapshot_id == SNAP_HN_SCORE_T12_B
    assert latest.metric_value == 12


def test_sql_market_filter_and_publisher_series(db_session: Session) -> None:
    service = AnalyticsService.from_session(db_session)
    id_rows = service.get_metric_observations(
        ObservationQuery(
            source_code="youtube",
            metric_name="view_count",
            content_item_id=YT_VIDEO_ID,
            market_id=MARKET_IDS["ID"],
        )
    )
    assert [row.metric_value for row in id_rows.observations] == [100, 150, 200]
    sg_rows = service.get_metric_observations(
        ObservationQuery(
            source_code="youtube",
            metric_name="view_count",
            content_item_id=YT_VIDEO_ID,
            market_id=MARKET_IDS["SG"],
        )
    )
    assert sg_rows.empty
    subs = service.get_publisher_metric_series(YT_CHANNEL_ID, "subscriber_count")
    assert [row.metric_value for row in subs.observations] == [50, 60]


def test_sql_like_count_gap_is_not_filled(db_session: Session) -> None:
    series = AnalyticsService.from_session(db_session).get_content_metric_series(
        YT_VIDEO_ID, "like_count"
    )
    assert [row.observed_at.hour for row in series.observations] == [10, 15]


def test_sql_aggregates_and_read_only(db_session: Session) -> None:
    service = AnalyticsService.from_session(db_session)
    query = ObservationQuery(content_item_id=YT_VIDEO_ID, metric_name="view_count")
    before = {
        row.id: (row.metric_value, row.observed_at, row.collected_at)
        for row in db_session.scalars(
            select(MetricSnapshot).where(MetricSnapshot.content_item_id == YT_VIDEO_ID)
        )
    }
    summary = service.summarize(query, aggregation=Aggregation.LATEST_VALUE)
    assert summary.origin == "trendora_derived"
    assert summary.value == 200
    assert summary.observation_count == 3
    after = {
        row.id: (row.metric_value, row.observed_at, row.collected_at)
        for row in db_session.scalars(
            select(MetricSnapshot).where(MetricSnapshot.content_item_id == YT_VIDEO_ID)
        )
    }
    assert before == after
    assert not db_session.deleted
    naive = datetime(2026, 8, 21, 12, 0)
    from trendora.analytics.exceptions import AnalyticsQueryError

    with pytest.raises(AnalyticsQueryError):
        service.get_metric_series(ObservationQuery(observed_from=naive))
