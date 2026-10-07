"""Research-to-planner import mapping, immutable origin, and source expiry (P3).

An import resolves a selected idea or brief from a persisted report on the
server, maps it onto the existing planner fields, and records an immutable
origin: which report, which item, the generated parent context, and minimal
source references. No full report and no raw API metadata are copied into
planner storage.

Expiry is derived from each source's original trusted collection time held in
the report snapshot, never from import time or report creation time. The
history visibility window is a separate read rule and does not renew source
lifetimes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from trendora.models.planner import PlannerPost, PlannerPostOriginSource
from trendora.reference import RETENTION_POLICIES

DEFAULT_RETENTION_DAYS = 30


class ImportSelectionError(Exception):
    """The selected item or its chain cannot be resolved."""


class ImportOverflowError(Exception):
    """A mapped field exceeds the existing planner limit."""


def _retention_days_for(source_code: str) -> int:
    """Return the shortest applicable retention for a source.

    A source the deployment knows about yields its documented policy; anything
    else falls back to the conservative application default rather than an
    unbounded lifetime.
    """
    matches = [
        int(policy["retention_days"])
        for policy in RETENTION_POLICIES
        if str(policy.get("code", "")).startswith(f"{source_code}_")
    ]
    if not matches:
        return DEFAULT_RETENTION_DAYS
    return min(matches)


def _parse_collected_at(value: Any, *, now: datetime) -> tuple[datetime | None, str]:
    """Parse a collection timestamp; reject anything not trustworthy.

    Returns ``(datetime|None, state)``. A missing, malformed, or future value
    is ``unresolved``: it must never qualify as fresh or extend retention.
    """
    if not isinstance(value, str) or not value:
        return None, "unresolved"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None, "unresolved"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed > now + timedelta(minutes=5):
        return None, "unresolved"
    return parsed, "available"


def _reference_index(snapshot: dict) -> dict[tuple[str, str], dict]:
    index: dict[tuple[str, str], dict] = {}
    for reference in (snapshot.get("research") or {}).get("references") or []:
        key = (reference.get("source_code"), reference.get("content_external_id"))
        index[key] = reference
    return index


def _citation_reference_keys(snapshot: dict, citations: list[dict]) -> list[tuple[str, str]]:
    """Resolve every citation, including patterns, to reference keys.

    A fact/observation citation names a reference directly. A pattern citation
    has no reference field, so its supporting reference ids are read from the
    evidence pack. A citation that resolves to nothing contributes no key.
    """
    index = _reference_index(snapshot)
    patterns = {
        pattern.get("observation_type"): pattern
        for pattern in ((snapshot.get("evidence") or {}).get("patterns") or [])
    }
    keys: list[tuple[str, str]] = []

    def _add(key: tuple[str, str]) -> None:
        if key in index and key not in keys:
            keys.append(key)

    for citation in citations:
        kind = citation.get("kind")
        if kind == "pattern":
            pattern = patterns.get(citation.get("observation_type"))
            if pattern is None:
                continue
            for reference in (
                list(pattern.get("matching_reference_ids") or [])
                + list(pattern.get("non_matching_reference_ids") or [])
            ):
                if isinstance(reference, dict):
                    _add((reference.get("source_code"), reference.get("content_external_id")))
            continue
        reference = citation.get("reference")
        if isinstance(reference, dict):
            _add((reference.get("source_code"), reference.get("content_external_id")))
    return keys


def build_origin_sources(
    snapshot: dict,
    origin: dict,
    *,
    provenance: str,
    now: datetime,
    source_expires_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Minimal source records for the citation chain in this origin.

    Only identity, URL, and the original trusted collection time are kept.
    Sources are resolved through the full citation chain, patterns included.

    A recovery with a server-verified original expiry has authenticated
    collection dates without changing its provenance. Other client snapshots
    remain unresolved. Missing or future timestamps never extend retention.
    """
    index = _reference_index(snapshot)
    trusted_recovery = (
        provenance == "client_supplied" and isinstance(source_expires_at, datetime)
        and source_expires_at.utcoffset() is not None and source_expires_at > now
    )
    trust_snapshot = provenance == "server_generated" or trusted_recovery
    sources: list[dict[str, Any]] = []
    for key in _citation_reference_keys(snapshot, origin.get("citations") or []):
        reference = index.get(key)
        if reference is None:
            continue
        retention = _retention_days_for(str(reference.get("source_code") or ""))
        collected: datetime | None = None
        if trust_snapshot:
            collected, _state = _parse_collected_at(reference.get("collected_at"), now=now)
        if collected is None:
            # No trustworthy collection time: keep the identity, mark it
            # unresolved, and bound cleanup at ``now`` so it never extends life.
            expires_at = now
        else:
            expires_at = collected + timedelta(days=retention)
            if source_expires_at is not None:
                expires_at = min(expires_at, source_expires_at)
        sources.append(
            {
                "source_code": reference.get("source_code"),
                "content_external_id": reference.get("content_external_id"),
                "url": reference.get("url"),
                "collected_at": collected,
                "retention_days": retention,
                "expires_at": expires_at,
            }
        )
    return sources


def persist_origin_sources(
    session: Session, *, post_id: UUID, sources: list[dict[str, Any]]
) -> None:
    for source in sources:
        session.add(
            PlannerPostOriginSource(
                post_id=post_id,
                source_code=source["source_code"],
                content_external_id=source["content_external_id"],
                url=source["url"],
                collected_at=source["collected_at"],
                retention_days=source["retention_days"],
                expires_at=source["expires_at"],
            )
        )


def _clip(value: str, limit: int, label: str) -> str:
    if len(value) > limit:
        raise ImportOverflowError(
            f"{label} exceeds the planner limit of {limit} characters"
        )
    return value


def map_idea(idea: dict) -> dict[str, str]:
    title = _clip(str(idea.get("title", "")).strip(), 200, "title")
    if not title:
        raise ImportSelectionError("selected idea has no title")
    return {
        "title": title,
        "hook": "",
        "creative_brief": _clip(f"Angle: {idea.get('angle', '')}".strip(), 20_000, "creative brief"),
    }


def map_brief(brief: dict, parent_idea: dict) -> dict[str, str]:
    title = _clip(str(parent_idea.get("title", "")).strip(), 200, "title")
    if not title:
        raise ImportSelectionError("parent idea has no title")
    outline = brief.get("outline") or []
    numbered = "\n".join(
        f"{index + 1}. {line}" for index, line in enumerate(outline)
    )
    parts = [
        f"Angle: {parent_idea.get('angle', '')}".strip(),
        f"Objective: {brief.get('objective', '')}".strip(),
        f"Format: {brief.get('format', '')}".strip(),
    ]
    if numbered:
        parts.append(numbered)
    scope = "\n".join(part for part in parts if part)
    return {
        "title": title,
        "hook": _clip(str(brief.get("hook", "")), 1_000, "hook"),
        "creative_brief": _clip(scope, 20_000, "creative brief"),
    }


def resolve_selection(
    snapshot: dict, *, item_kind: str, item_index: int
) -> tuple[dict[str, str], dict]:
    """Resolve the selected item and its immutable origin context."""
    ideation = snapshot.get("ideation") or {}
    ideas = ideation.get("content_ideas") or []
    briefs = ideation.get("content_briefs") or []

    if item_kind == "idea":
        if item_index < 0 or item_index >= len(ideas):
            raise ImportSelectionError("idea index is out of range")
        idea = ideas[item_index]
        fields = map_idea(idea)
        citations = idea.get("citations") or []
        origin = {
            "item_kind": "idea",
            "item_index": item_index,
            "parent_idea_index": None,
            "context": {"title": idea.get("title", ""), "angle": idea.get("angle", "")},
            "citations": citations,
        }
        return fields, origin

    if item_kind == "brief":
        if item_index < 0 or item_index >= len(briefs):
            raise ImportSelectionError("brief index is out of range")
        brief = briefs[item_index]
        parent_index = brief.get("idea_index")
        if not isinstance(parent_index, int) or parent_index < 0 or parent_index >= len(ideas):
            raise ImportSelectionError("brief parent idea is missing")
        parent = ideas[parent_index]
        fields = map_brief(brief, parent)
        citations = brief.get("citations") or []
        origin = {
            "item_kind": "brief",
            "item_index": item_index,
            "parent_idea_index": parent_index,
            "context": {
                "parent_title": parent.get("title", ""),
                "parent_angle": parent.get("angle", ""),
                "objective": brief.get("objective", ""),
                "format": brief.get("format", ""),
                "hook": brief.get("hook", ""),
                "outline": list(brief.get("outline") or []),
            },
            "citations": citations,
        }
        return fields, origin

    raise ImportSelectionError("item_kind must be idea or brief")


def source_state(
    *, collected_at: datetime | None, expires_at: datetime, now: datetime
) -> str:
    if collected_at is None:
        return "unresolved"
    if now >= expires_at:
        return "expired"
    return "available"


def read_origin(
    session: Session,
    *,
    post_id: UUID,
    now: datetime,
    can_read_report: bool,
) -> dict[str, Any] | None:
    """Resolve the stored origin with per-source state.

    ``can_read_report`` reflects the caller's current history access. When it
    is false, source identities are restricted rather than shown; the authored
    post and generated context remain.
    """
    post = session.get(PlannerPost, post_id)
    if post is None or post.origin is None:
        return None
    origin = dict(post.origin)
    sources = session.execute(
        select(PlannerPostOriginSource).where(
            PlannerPostOriginSource.post_id == post_id
        )
    ).scalars().all()
    resolved_sources = []
    for source in sources:
        if not can_read_report:
            state = "restricted"
        else:
            state = source_state(
                collected_at=source.collected_at,
                expires_at=source.expires_at,
                now=now,
            )
        if state == "available":
            resolved_sources.append(
                {
                    "source_code": source.source_code,
                    "content_external_id": source.content_external_id,
                    "state": state,
                    "url": source.url,
                }
            )
        else:
            # expired, restricted, or unresolved: keep the identity for
            # attribution but never surface a link that is not current.
            resolved_sources.append(
                {
                    "source_code": source.source_code,
                    "content_external_id": source.content_external_id,
                    "state": state,
                    "url": None,
                }
            )
    return {
        "report_id": origin.get("report_id"),
        "item_kind": origin.get("item_kind"),
        "item_index": origin.get("item_index"),
        "parent_idea_index": origin.get("parent_idea_index"),
        "provenance": origin.get("provenance", "legacy_unclassified"),
        "context": origin.get("context", {}),
        "sources": resolved_sources,
    }


def purge_expired_origin_sources(session: Session, now: datetime) -> int:
    """Delete expired source-metadata rows; never touch the authored post."""
    result = session.execute(
        delete(PlannerPostOriginSource).where(
            PlannerPostOriginSource.expires_at <= now
        )
    )
    return int(result.rowcount or 0)
