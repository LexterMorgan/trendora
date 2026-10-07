"""Explicit source-data expiry; no scheduler, startup hook, or provider calls.

Run ``python -m trendora.retention --database-env NAME`` to inspect counts.
Only ``--apply`` commits changes. The command reads that one environment
variable, never application dotenv files or provider settings. Database access
and scheduling remain separate operator actions.

YouTube's non-authorized API data has a 30-day refresh/delete limit. Other
report sources use the existing conservative application TTL, not a claimed
provider requirement. Report fingerprints and authored planner fields survive
expiry; the original source-bearing report body does not.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from trendora.models import ContentItem, MetricSnapshot, Publisher, Source
from trendora.models.planner import PlannerPost, PlannerPostOriginSource
from trendora.models.research import ResearchReportRecord
from trendora.planner_origin import _retention_days_for

EXPIRED_STATUS = "source_data_expired"
_EXTERNAL_ID_MARKER = "retention-expired:"


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def report_source_deadline(snapshot: dict[str, Any], *, now: datetime) -> datetime | None:
    """Derive the original bound only while source timestamps are trusted."""
    research = snapshot.get("research") if isinstance(snapshot, dict) else None
    references = research.get("references") if isinstance(research, dict) else None
    if not isinstance(references, list) or not references:
        return None
    deadlines = []
    for reference in references:
        if not isinstance(reference, dict):
            return None
        collected = _timestamp(reference.get("collected_at"))
        if collected is None or collected > now:
            return None
        days = _retention_days_for(str(reference.get("source_code") or ""))
        deadlines.append(collected + timedelta(days=days))
    return min(deadlines)


def report_sources_expired(
    snapshot: dict[str, Any], *, provenance: str, now: datetime,
    source_expires_at: datetime | None = None,
) -> bool:
    """Expiry of source-bearing data, never inferred from report save time.

    A verified recovery retains its separately stored original bound; its
    provenance remains client-supplied. Unknown collection dates cannot
    establish freshness. An
    empty report with no source or generated material has nothing to expire.
    """
    if not isinstance(snapshot, dict) or snapshot.get("status") == EXPIRED_STATUS:
        return True
    research = snapshot.get("research")
    references = research.get("references") if isinstance(research, dict) else None
    if not references:
        for field in ("evidence", "interpretation", "strategy", "ideation"):
            output = snapshot.get(field)
            if isinstance(output, dict):
                if any(value for key, value in output.items() if key != "model_provenance"):
                    return True
            elif output:
                return True
        return False
    if provenance not in {"server_generated", "client_supplied"}:
        return True
    trusted = _timestamp(source_expires_at)
    if provenance == "client_supplied" and trusted is None:
        return True
    original = report_source_deadline(snapshot, now=now)
    if original is None:
        return True
    return min(original, trusted) <= now if trusted is not None else original <= now


def _bounded_expiry(
    *, source: str, collected_at: Any, expires_at: Any, now: datetime
) -> bool:
    collected = _timestamp(collected_at)
    expires = _timestamp(expires_at)
    if collected is None or collected > now or expires is None:
        return True
    bound = collected + timedelta(days=_retention_days_for(source))
    return min(expires, bound) <= now


def expire_source_data(
    session: Session, *, now: datetime, apply: bool = False
) -> dict[str, int]:
    """Count or expire source data in the caller's transaction.

    Dry runs assign/delete nothing and never flush or commit. Apply preserves
    internal identities, original replay hashes, membership and all authored
    planner fields. The caller must commit or roll back the whole operation.
    """
    now = _timestamp(now)
    if now is None:
        raise ValueError("retention requires a timezone-aware current time")
    def rows(model):
        statement = select(model)
        if model is PlannerPost:
            statement = statement.where(PlannerPost.origin.is_not(None))
        if apply:
            statement = statement.with_for_update()
        with session.no_autoflush:
            return session.scalars(statement).all()

    sources = {row.id: row.code for row in rows(Source)}
    reports = rows(ResearchReportRecord)
    posts = rows(PlannerPost)
    origin_sources = rows(PlannerPostOriginSource)
    # Match ingestion's publisher -> content -> metric lock order.
    publishers = rows(Publisher)
    content = rows(ContentItem)
    metrics = rows(MetricSnapshot)
    counts = {
        "reports_expired": 0,
        "origins_cleared": 0,
        "origin_sources_deleted": 0,
        "metrics_deleted": 0,
        "content_cleared": 0,
        "publishers_cleared": 0,
    }

    expired_report_ids: set[str] = set()
    for row in reports:
        if (row.status == EXPIRED_STATUS and isinstance(row.report, dict)
                and set(row.report) == {"status", "expired_at"}
                and row.report.get("status") == EXPIRED_STATUS):
            expired_report_ids.add(str(row.id))
            continue
        if not report_sources_expired(
            row.report, provenance=row.snapshot_origin, now=now,
            source_expires_at=row.source_expires_at,
        ):
            continue
        expired_report_ids.add(str(row.id))
        counts["reports_expired"] += 1
        if apply:
            row.status = EXPIRED_STATUS
            row.report = {"status": EXPIRED_STATUS, "expired_at": now.isoformat()}

    expired_post_ids = {
        row.post_id for row in origin_sources
        if _bounded_expiry(
            source=row.source_code, collected_at=row.collected_at,
            expires_at=row.expires_at, now=now,
        )
    }
    report_deadlines = {str(row.id): row.source_expires_at for row in reports}
    for post in posts:
        if not isinstance(post.origin, dict):
            continue
        if post.origin.get("provenance") != "server_generated" and not (
            post.origin.get("provenance") == "client_supplied"
            and _timestamp(report_deadlines.get(str(post.origin.get("report_id")))) is not None
        ):
            expired_post_ids.add(post.id)
        if str(post.origin.get("report_id")) in expired_report_ids:
            expired_post_ids.add(post.id)
        if post.id not in expired_post_ids:
            continue
        origin = {key: post.origin[key] for key in (
            "report_id", "item_kind", "item_index", "parent_idea_index", "provenance"
        ) if key in post.origin}
        origin.update(context={}, citations=[], source_state="expired")
        if origin != post.origin:
            counts["origins_cleared"] += 1
            if apply:
                post.origin = origin
                # Include the original timestamp in UPDATE so the authored
                # draft is not reordered by TimestampMixin's onupdate hook.
                flag_modified(post, "updated_at")
    for row in origin_sources:
        if row.post_id in expired_post_ids:
            counts["origin_sources_deleted"] += 1
            if apply:
                session.delete(row)

    for row in metrics:
        source = sources.get(row.source_id, "")
        if source == "youtube":
            expired = _bounded_expiry(
                source=source, collected_at=row.collected_at,
                expires_at=row.retain_until, now=now,
            )
        else:
            expires = _timestamp(row.retain_until)
            expired = row.retain_until is not None and (expires is None or expires <= now)
        if expired:
            counts["metrics_deleted"] += 1
            if apply:
                session.delete(row)

    for rows, fields, count in (
        (content, ("title", "description", "url", "published_at", "source_metadata"), "content_cleared"),
        (publishers, ("name", "url", "source_metadata"), "publishers_cleared"),
    ):
        for row in rows:
            expires = _timestamp(row.retain_until)
            source = sources.get(row.source_id, "")
            if source == "youtube":
                # Ingested catalog rows store the trusted original expiry
                # bound, not a publication or last-access timestamp.
                expired = expires is None or expires <= now or expires > now + timedelta(days=30)
            else:
                expired = row.retain_until is not None and (expires is None or expires <= now)
            if not expired:
                continue
            marker = f"{_EXTERNAL_ID_MARKER}{row.id}"
            if row.external_id == marker and all(getattr(row, field) is None for field in fields):
                continue
            counts[count] += 1
            if apply:
                for field in fields:
                    setattr(row, field, None)
                # A YouTube-provided ID is source data too. Preserve the
                # internal PK/FKs without retaining that expired external ID.
                row.external_id = marker
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect source expiry; --apply commits deletion.")
    parser.add_argument(
        "--database-env", required=True,
        help="Name of the explicitly supplied PostgreSQL URL environment variable (no dotenv).",
    )
    parser.add_argument("--apply", action="store_true", help="Commit source expiry, preserving authored posts and replay keys.")
    args = parser.parse_args(argv)
    database_url = os.environ.get(args.database_env, "").strip()
    if not database_url:
        print("The named database environment variable is not set.", file=sys.stderr)
        return 2
    from trendora.config import Settings

    try:
        database_url = Settings.normalize_postgres_url(database_url)
    except ValueError:
        print("Retention requires an explicitly supplied PostgreSQL URL.", file=sys.stderr)
        return 2
    engine = None
    try:
        engine = create_engine(database_url)
        with Session(engine) as session:
            counts = expire_source_data(
                session, now=datetime.now(timezone.utc), apply=args.apply
            )
            if args.apply:
                session.commit()
            else:
                session.rollback()
        print(json.dumps({"mode": "apply" if args.apply else "dry_run", **counts}, sort_keys=True))
        return 0
    except SQLAlchemyError:
        print("Source expiry failed; the transaction was not committed.", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
