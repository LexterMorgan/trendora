"""ForecastingService reads M5 PostgreSQL series. Rolls back. No source APIs."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from trendora.analytics.repository import ObservationQuery
from trendora.analytics.service import AnalyticsService
from trendora.forecasting import ForecastModel, ForecastRequest, ForecastingService
from trendora.models import MetricSnapshot
from tests.fixtures.analytics_observations import T15, YT_VIDEO_ID, seed_analytics_fixture

pytestmark = pytest.mark.integration


@pytest.fixture
def db_session(test_engine) -> Session:
    connection = test_engine.connect()
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


def test_naive_forecast_reads_analytics_without_writing(db_session: Session) -> None:
    before = {
        row.id: row.metric_value
        for row in db_session.scalars(
            select(MetricSnapshot).where(MetricSnapshot.content_item_id == YT_VIDEO_ID)
        )
    }
    service = ForecastingService(AnalyticsService.from_session(db_session))
    result = service.forecast(
        ForecastRequest(
            query=ObservationQuery(
                source_code="youtube",
                metric_name="view_count",
                content_item_id=YT_VIDEO_ID,
            ),
            model=ForecastModel.NAIVE,
            horizon=2,
            interval=timedelta(days=1),
        )
    )
    assert [point.value for point in result.points] == [200.0, 200.0]
    assert result.points[0].at == T15 + timedelta(days=1)
    assert result.origin == "trendora_forecast"
    after = {
        row.id: row.metric_value
        for row in db_session.scalars(
            select(MetricSnapshot).where(MetricSnapshot.content_item_id == YT_VIDEO_ID)
        )
    }
    assert before == after
    assert not db_session.deleted
    assert not db_session.dirty
