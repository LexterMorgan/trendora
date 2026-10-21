"""History search contracts, evaluated offline without a database connection."""

from datetime import date, datetime, timedelta, timezone
import re
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import operators

from trendora.models.research import ResearchReportRecord
from trendora.research.repository import get_report_records


NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)
CUTOFF = NOW - timedelta(days=30)


def record(number, **values):
    return ResearchReportRecord(
        **{
            "id": UUID(int=number),
            "created_at": NOW - timedelta(minutes=number),
            "created_by": UUID(int=number % 2 + 1),
            "topic": "Other topic",
            "status": "completed",
            "markets": [],
            "source_codes": [],
            "date_from": date(2026, 8, 1),
            "date_to": date(2026, 8, 31),
            "report": {"status": "completed"},
            "snapshot_origin": "server_generated",
            **values,
        }
    )


class MemoryQuery:
    """Evaluate the SQL predicates and pagination against disconnected ORM rows."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.predicates = []
        self.page_offset = None
        self.page_limit = None

    def filter(self, expression):
        self.predicates.append(expression)
        value = expression.right.value
        if expression.operator is operators.icontains_op:
            escape = expression.modifiers["escape"]
            literal = re.sub(re.escape(escape) + r"(.)", r"\1", value)
            matches = lambda row: literal.lower() in getattr(row, expression.left.key).lower()
        else:
            assert expression.operator in (operators.eq, operators.ge, operators.le)
            matches = lambda row: expression.operator(getattr(row, expression.left.key), value)
        self.rows = [row for row in self.rows if matches(row)]
        return self

    def count(self):
        assert self.page_offset is None and self.page_limit is None
        self.count_predicates = tuple(self.predicates)
        return len(self.rows)

    def order_by(self, *expressions):
        for expression in reversed(expressions):
            assert expression.modifier is operators.desc_op
            self.rows.sort(key=lambda row: getattr(row, expression.element.key), reverse=True)
        return self

    def offset(self, value):
        self.page_offset = value
        return self

    def limit(self, value):
        self.page_limit = value
        return self

    def all(self):
        assert tuple(self.predicates) == self.count_predicates
        return self.rows[self.page_offset:self.page_offset + self.page_limit]


class MemorySession:
    def __init__(self, rows):
        self.history = MemoryQuery(rows)

    def query(self, model):
        assert model is ResearchReportRecord
        return self.history


def test_searches_beyond_first_page_before_count_and_offset_across_creators():
    session = MemorySession([
        *[record(number) for number in range(1, 121)],
        record(121, topic="Climate education"),
        record(122, topic="CLIMATE policy"),
        record(123, topic="Climate action"),
        record(124, topic="Climate hidden", created_at=CUTOFF - timedelta(seconds=1)),
    ])

    summaries, total = get_report_records(
        session, q="  cLiMaTe  ", limit=1, offset=1, visible_from=CUTOFF, now=NOW,
    )

    assert total == 3
    assert [summary["id"] for summary in summaries] == [str(UUID(int=122))]
    assert "created_by" not in str(select(ResearchReportRecord.id).where(*session.history.predicates))


def test_combines_topic_outcome_dates_and_visibility_before_pagination():
    rows = [
        record(1, topic="Climate", status="no_evidence"),
        record(2, topic="Climate", date_from=date(2026, 9, 1), date_to=date(2026, 9, 2)),
        record(3, topic="Climate", created_at=CUTOFF - timedelta(seconds=1)),
        record(4, topic="Climate", created_at=CUTOFF),
        record(5),
    ]
    summaries, total = get_report_records(
        MemorySession(rows), q="climate", status="completed",
        date_from=date(2026, 8, 31), date_to=date(2026, 8, 31),
        visible_from=CUTOFF, now=NOW,
    )
    assert total == 1
    assert [summary["id"] for summary in summaries] == [str(UUID(int=4))]


@pytest.mark.parametrize(
    ("bounds", "expected"),
    [
        ({"date_from": date(2026, 8, 31)}, [4, 3, 2]),
        ({"date_to": date(2026, 8, 1)}, [3, 2, 1]),
        ({"date_from": date(2026, 8, 1), "date_to": date(2026, 8, 31)}, [3, 2]),
    ],
)
def test_requested_window_overlap_is_inclusive_and_supports_one_sided_bounds(bounds, expected):
    rows = [
        record(1, date_from=date(2026, 7, 1), date_to=date(2026, 7, 31)),
        record(2),
        record(3, date_from=date(2026, 7, 1), date_to=date(2026, 9, 30)),
        record(4, date_from=date(2026, 9, 1), date_to=date(2026, 9, 30)),
    ]
    for row in rows:
        row.created_at = NOW
    summaries, total = get_report_records(MemorySession(rows), now=NOW, **bounds)
    assert total == len(expected)
    assert [summary["id"] for summary in summaries] == [str(UUID(int=n)) for n in expected]


@pytest.mark.parametrize("q", ["100%", "a_b", r"a\b", "a/b", "%' OR 1=1 --"])
def test_topic_substring_escapes_like_metacharacters_and_binds_values(q):
    session = MemorySession([record(1, topic=f"Before {q} after"), record(2, topic="aXb 1000")])
    summaries, total = get_report_records(session, q=q, now=NOW)
    assert total == 1
    assert summaries[0]["id"] == str(UUID(int=1))
    compiled = select(ResearchReportRecord.id).where(*session.history.predicates).compile(
        dialect=postgresql.dialect(),
    )
    assert "ILIKE" in str(compiled) and "ESCAPE" in str(compiled)
    assert q not in str(compiled)
    assert compiled.params


def test_filters_stored_outcome_while_returning_effective_expired_read_status():
    expired = record(1, report={"research": {"references": [{
        "source_code": "youtube", "collected_at": (NOW - timedelta(days=31)).isoformat(),
    }]}})
    swept = record(2, status="source_data_expired", report={"status": "source_data_expired"})
    summaries, total = get_report_records(
        MemorySession([expired, swept]), status="completed", now=NOW,
    )
    assert total == 1
    assert summaries[0]["status"] == "source_data_expired"
    assert expired.status == "completed"
    summaries, total = get_report_records(
        MemorySession([expired, swept]), status="source_data_expired", now=NOW,
    )
    assert total == 1
    assert summaries[0]["id"] == str(swept.id)


@pytest.mark.parametrize("q", [None, "", "   "])
def test_empty_search_preserves_admin_history_and_timestamp_id_order(q):
    old = NOW - timedelta(days=120)
    rows = [record(1, created_at=old), record(2, created_at=old), record(3)]
    summaries, total = get_report_records(MemorySession(rows), q=q, visible_from=None, now=NOW)
    assert total == 3
    assert [summary["id"] for summary in summaries] == [str(rows[n].id) for n in (2, 1, 0)]


def test_empty_page_keeps_filtered_total():
    summaries, total = get_report_records(
        MemorySession([record(1, topic="Climate")]), q="climate", offset=50, now=NOW,
    )
    assert summaries == []
    assert total == 1


def test_topic_query_length_is_bounded_before_querying():
    with pytest.raises(ValueError, match="200"):
        get_report_records(MemorySession([]), q="x" * 201, now=NOW)
    summaries, total = get_report_records(
        MemorySession([record(1, topic="x" * 200)]), q="x" * 200, now=NOW,
    )
    assert total == len(summaries) == 1
