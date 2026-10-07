"""Offline contract checks for the planner ORM records (P2A Task 2).

Inspection only: no engine, no connection, no migration run. These pin the
schema facts the migration and service rely on: SQL ``DATE`` planning dates,
non-cascading membership foreign keys, the unique creator/request key behind
retry-safe creation, the status check, strictly positive counters, and the
``gen_random_uuid()`` id defaults the ORM declares. The migration revision is
executed against a recording ``op`` stand-in so its table definitions can be
rebuilt and compared offline; alembic itself never runs here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

from trendora.models.planner import PlannerPost, PlannerPostActivity

MEMBERSHIP_KEYS = "memberships.user_id"

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0004_planner_posts.py"
)
PLANNER_TABLES = ("planner_posts", "planner_post_activity")


def _unique(table: sa.Table, *columns: str) -> sa.UniqueConstraint:
    wanted = set(columns)
    matches = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
        and set(constraint.columns.keys()) == wanted
    ]
    assert len(matches) == 1, f"expected one unique constraint on {sorted(wanted)}"
    return matches[0]


def _checks(table: sa.Table) -> dict[str, str]:
    return {
        constraint.name: "".join(str(constraint.sqltext).split())
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }


def _indexes(table: sa.Table) -> dict[str, list[str]]:
    return {index.name: [c.name for c in index.columns] for index in table.indexes}


def _foreign_keys(column: sa.Column) -> list[sa.ForeignKey]:
    return list(column.foreign_keys)


def test_planner_metadata_matches_contract() -> None:
    post = PlannerPost.__table__
    activity = PlannerPostActivity.__table__

    assert isinstance(post.c.planned_date.type, sa.Date)
    assert isinstance(post.c.asset_links.type, JSONB)

    for column in ("created_by", "updated_by", "assignee_id"):
        foreign_keys = _foreign_keys(post.c[column])
        assert len(foreign_keys) == 1, f"{column} must reference exactly one table"
        assert foreign_keys[0].target_fullname == MEMBERSHIP_KEYS
        assert foreign_keys[0].ondelete is None, f"{column} must not cascade deletes"
    assert post.c.assignee_id.nullable is True
    assert post.c.created_by.nullable is False
    assert post.c.updated_by.nullable is False

    request_key = _unique(post, "created_by", "create_request_id")
    assert request_key.name == "uq_planner_posts_created_by"
    assert post.c.create_request_id.nullable is False
    assert post.c.create_payload_hash.type.length == 64
    assert post.c.create_payload_hash.nullable is False

    checks = _checks(post)
    assert checks["ck_planner_posts_status"] == "statusIN('idea','working')"
    assert checks["ck_planner_posts_version_positive"] == "version>0"
    assert (
        checks["ck_planner_posts_content_revision_positive"] == "content_revision>0"
    )
    assert post.c.version.default.arg == 1
    assert post.c.content_revision.default.arg == 1

    assert _indexes(post)["ix_planner_posts_updated_at"] == ["updated_at", "id"]
    assert post.c.archived_at.nullable is True

    post_fk = _foreign_keys(activity.c.post_id)
    actor_fk = _foreign_keys(activity.c.actor_id)
    assert len(post_fk) == 1 and post_fk[0].target_fullname == "planner_posts.id"
    assert len(actor_fk) == 1 and actor_fk[0].target_fullname == MEMBERSHIP_KEYS
    assert post_fk[0].ondelete is None and actor_fk[0].ondelete is None
    assert _checks(activity)["ck_planner_post_activity_event_type"] == (
        "event_typeIN('created','updated','archived','restored')"
    )
    assert isinstance(activity.c.details.type, JSONB)
    assert _indexes(activity)["ix_planner_post_activity_post_id"] == [
        "post_id",
        "created_at",
        "id",
    ]


class _CaptureOp:
    """Stand-in for alembic's ``op``: records DDL, never opens a connection."""

    def __init__(self) -> None:
        self.tables: dict[str, tuple] = {}
        self.dropped: list[str] = []
        self.executed: list[str] = []

    def create_table(self, name: str, *elements, **kwargs) -> None:
        self.tables[name] = elements

    def create_index(self, name: str, table_name: str, columns, **kwargs) -> None:
        return None

    def execute(self, statement, *args, **kwargs) -> None:
        self.executed.append(str(statement))

    def drop_table(self, name: str, **kwargs) -> None:
        self.dropped.append(name)


def _load_revision(monkeypatch):
    spec = importlib.util.spec_from_file_location("trendora_migration_0004", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    capture = _CaptureOp()
    monkeypatch.setattr(revision, "op", capture)
    return revision, capture


def _rebuilt_tables(capture: _CaptureOp) -> dict[str, sa.Table]:
    """Rebuild the revision's tables the way alembic's naming context would."""
    metadata = sa.MetaData(
        naming_convention=PlannerPost.__table__.metadata.naming_convention
    )
    sa.Table(
        "memberships", metadata, sa.Column("user_id", sa.Uuid(), primary_key=True)
    )
    return {
        name: sa.Table(name, metadata, *elements)
        for name, elements in capture.tables.items()
    }


def _orm_table(name: str) -> sa.Table:
    return {cls.__table__.name: cls.__table__ for cls in (PlannerPost, PlannerPostActivity)}[
        name
    ]


def _server_default(column: sa.Column) -> str | None:
    if column.server_default is None:
        return None
    arg = column.server_default.arg
    if isinstance(arg, str):
        return arg.strip()
    return str(arg.compile(dialect=postgresql.dialect())).strip()


def test_migration_and_orm_declare_the_same_server_defaults(monkeypatch) -> None:
    revision, capture = _load_revision(monkeypatch)
    revision.upgrade()
    tables = _rebuilt_tables(capture)

    assert set(tables) == set(PLANNER_TABLES)
    for name in PLANNER_TABLES:
        migrated, orm = tables[name], _orm_table(name)
        # 0004 defines the base columns; later migrations may add more.
        assert set(migrated.c.keys()) <= set(orm.c.keys()), name
        for column in migrated.c:
            assert _server_default(column) == _server_default(orm.c[column.name]), (
                f"{name}.{column.name}"
            )
        assert _server_default(migrated.c.id) == "gen_random_uuid()"
        assert migrated.c.id.primary_key and migrated.c.id.nullable is False


def test_id_is_filled_by_the_database_not_by_the_client(monkeypatch) -> None:
    """No INSERT ever carries ``id``: no Python-side default, and the
    ``CREATE TABLE`` DDL is what supplies ``gen_random_uuid()``."""
    revision, capture = _load_revision(monkeypatch)
    revision.upgrade()
    tables = _rebuilt_tables(capture)

    for name in PLANNER_TABLES:
        migrated, orm = tables[name], _orm_table(name)
        ddl = str(
            sa.schema.CreateTable(migrated).compile(dialect=postgresql.dialect())
        )
        assert "DEFAULT gen_random_uuid()" in ddl, name
        assert migrated.c.id.default is None, f"{name}: python-side id default"
        assert orm.c.id.default is None, f"{name}: python-side id default"


def test_downgrade_drops_only_the_planner_tables(monkeypatch) -> None:
    revision, capture = _load_revision(monkeypatch)
    revision.downgrade()

    assert capture.dropped == ["planner_post_activity", "planner_posts"]
