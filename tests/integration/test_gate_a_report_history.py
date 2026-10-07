"""Gate A: rolling 30-day window at the repository (real PostgreSQL)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from trendora.models.research import ResearchReportRecord
from trendora.research.repository import get_report_record_by_id, get_report_records

NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)
CUTOFF = NOW - timedelta(days=30)


@pytest.fixture
def report_session(approved_engine):
    session = Session(approved_engine)

    def wipe() -> None:
        session.rollback()
        session.query(ResearchReportRecord).delete()
        session.commit()

    wipe()
    try:
        yield session
    finally:
        wipe()
        session.close()


def _add(session: Session, *, created_at: datetime, id: UUID | None = None):
    record = ResearchReportRecord(
        status="completed",
        topic="topic",
        markets=["SG"],
        source_codes=["youtube"],
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 2),
        report={"status": "completed"},
    )
    record.created_at = created_at
    if id is not None:
        record.id = id
    session.add(record)
    session.commit()
    return record.id


class TestVisibilityWindow:
    def test_cutoff_is_inclusive(self, report_session) -> None:
        inside = _add(report_session, created_at=NOW - timedelta(days=29))
        boundary = _add(report_session, created_at=CUTOFF)
        _add(report_session, created_at=CUTOFF - timedelta(seconds=1))
        _add(report_session, created_at=NOW - timedelta(days=60))

        summaries, total = get_report_records(report_session, visible_from=CUTOFF)

        assert {summary["id"] for summary in summaries} == {
            str(inside),
            str(boundary),
        }
        assert total == 2

    def test_pagination_counts_visible_rows_only(self, report_session) -> None:
        visible = [
            _add(report_session, created_at=NOW - timedelta(days=offset))
            for offset in range(3)
        ]
        for offset in range(3):
            _add(report_session, created_at=NOW - timedelta(days=40 + offset))

        summaries, total = get_report_records(
            report_session, limit=2, offset=2, visible_from=CUTOFF
        )

        assert total == 3
        assert [summary["id"] for summary in summaries] == [str(visible[2])]

        empty_page, total_after = get_report_records(
            report_session, limit=2, offset=4, visible_from=CUTOFF
        )
        assert empty_page == []
        assert total_after == 3

    def test_admin_sees_full_history(self, report_session) -> None:
        _add(report_session, created_at=NOW - timedelta(days=1))
        _add(report_session, created_at=NOW - timedelta(days=120))

        summaries, total = get_report_records(report_session, visible_from=None)

        assert total == 2
        assert len(summaries) == 2

    def test_order_is_created_at_desc(self, report_session) -> None:
        older = _add(report_session, created_at=NOW - timedelta(days=2))
        newer = _add(report_session, created_at=NOW - timedelta(days=1))

        summaries, _ = get_report_records(report_session, visible_from=CUTOFF)

        assert [summary["id"] for summary in summaries] == [str(newer), str(older)]


class TestListAndDirectIdAgree:
    def test_visible_rows_fetchable_and_hidden_rows_not(
        self, report_session
    ) -> None:
        inside = _add(report_session, created_at=NOW - timedelta(days=29))
        outside = _add(report_session, created_at=NOW - timedelta(days=90))

        summaries, _ = get_report_records(report_session, visible_from=CUTOFF)
        listed = {summary["id"] for summary in summaries}
        assert str(inside) in listed
        assert str(outside) not in listed

        assert (
            get_report_record_by_id(report_session, str(inside), visible_from=CUTOFF)
            is not None
        )
        assert (
            get_report_record_by_id(report_session, str(outside), visible_from=CUTOFF)
            is None
        )
        assert (
            get_report_record_by_id(report_session, str(outside), visible_from=None)
            is not None
        )

    def test_admin_direct_id_fetches_hidden_row(self, report_session) -> None:
        hidden = _add(report_session, created_at=NOW - timedelta(days=400))
        assert (
            get_report_record_by_id(report_session, str(hidden), visible_from=None)
            is not None
        )


class TestTiebreak:
    def test_same_timestamp_orders_by_id_desc(self, report_session) -> None:
        low = UUID("00000000-0000-4000-8000-000000000001")
        high = UUID("00000000-0000-4000-8000-000000000002")
        _add(report_session, created_at=NOW, id=low)
        _add(report_session, created_at=NOW, id=high)

        summaries, _ = get_report_records(report_session, visible_from=None)

        assert [summary["id"] for summary in summaries] == [str(high), str(low)]
