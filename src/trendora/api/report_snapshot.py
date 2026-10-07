"""Canonical report-snapshot fingerprinting and strict recovery validation (P3).

The immutable report snapshot is exactly the six fields the report response
already carries: ``status``, ``research``, ``evidence``, ``interpretation``,
``strategy``, ``ideation``. Persistence metadata (report id, request id,
origin classification, timestamps) lives outside the snapshot and is never
fingerprinted.

Both the initial server save and a browser recovery POST hash the same
object under one canonical rule. A raw ``json.dumps`` is not enough: the
browser parses and re-stringifies the snapshot, so ``1.0`` becomes ``1`` and
key order changes. The canonical form below normalizes numbers and key order
so an equivalent snapshot replays instead of falsely conflicting.

Validation here is the trust boundary for client-supplied recovery. It is
stricter than the response models: unknown fields, non-finite numbers,
invalid relationships, unknown citation kinds, unsafe URLs, and duplicates
are rejected rather than coerced.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# Strict integer: rejects booleans, strings, and floats so a forged count or
# index cannot coerce into a valid-looking integer.
StrictInt = Annotated[int, Field(strict=True)]


def _check_date(value: str) -> str:
    """Exact ``YYYY-MM-DD`` calendar date; no timestamps, no shorthand."""
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("date must be an exact YYYY-MM-DD calendar date")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("date must be an exact YYYY-MM-DD calendar date") from exc
    return value

SNAPSHOT_FIELDS: tuple[str, ...] = (
    "status",
    "research",
    "evidence",
    "interpretation",
    "strategy",
    "ideation",
)

SCHEMA_VERSION = 1

# Recovery-only bounds. These are not applied retroactively to stored rows.
MAX_LIST = 100
MAX_REFERENCES = 100
MAX_TITLE = 300
MAX_DESCRIPTION = 5_000
MAX_CHANNEL_TITLE = 200
MAX_STATEMENT = 2_000
MAX_ANGLE = 1_000
MAX_OUTLINE_ITEM = 500
MAX_OUTLINE_ITEMS = 100
MAX_URL = 2_048
MAX_TOPIC = 500

_STATUSES = frozenset({
    "completed", "no_evidence", "research_completed", "content_unavailable",
    "insufficient_evidence", "research_unavailable",
})
_ALLOWED_URL_SCHEMES = ("http", "https")


def _canonicalize(value: Any) -> Any:
    """Normalize a JSON value so browser and server agree byte for byte.

    Integral floats become ints (``1.0`` -> ``1``), matching JavaScript's
    ``JSON.stringify``. Dict keys are sorted by the caller's ``sort_keys``.
    Non-finite floats are rejected here as a last line of defence.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("snapshot contains a non-finite number")
        if value.is_integer():
            return int(value)
        return value
    if isinstance(value, dict):
        return {str(key): _canonicalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    return value


def canonical_snapshot_bytes(snapshot: dict[str, Any]) -> bytes:
    """Return the canonical UTF-8 bytes both sides hash.

    Only the six snapshot fields are included. Extra keys are dropped so an
    outer envelope can never change the fingerprint.
    """
    projected = {field: _canonicalize(snapshot.get(field)) for field in SNAPSHOT_FIELDS}
    encoded = json.dumps(
        projected,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return encoded.encode("utf-8")


def snapshot_fingerprint(snapshot: dict[str, Any]) -> str:
    """Lowercase SHA-256 hex of the canonical snapshot bytes."""
    return hashlib.sha256(canonical_snapshot_bytes(snapshot)).hexdigest()


def _check_url(value: str) -> str:
    if len(value) > MAX_URL:
        raise ValueError(f"URL is longer than {MAX_URL} characters")
    parts = urlsplit(value)
    if parts.scheme not in _ALLOWED_URL_SCHEMES or not parts.hostname:
        raise ValueError("URL must be an http(s) URL with a host")
    if parts.username is not None or parts.password is not None:
        raise ValueError("URL must not embed credentials")
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Metrics(_Strict):
    view_count: StrictInt | None = None
    like_count: StrictInt | None = None
    comment_count: StrictInt | None = None
    reaction_count: StrictInt | None = None
    share_count: StrictInt | None = None


class _Reference(_Strict):
    source_code: str = Field(min_length=1, max_length=64)
    content_external_id: str = Field(min_length=1, max_length=256)
    url: str | None = None
    title: str | None = Field(default=None, max_length=MAX_TITLE)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)
    published_at: str | None = None
    channel_external_id: str | None = Field(default=None, max_length=256)
    channel_title: str | None = Field(default=None, max_length=MAX_CHANNEL_TITLE)
    market_contexts: list[str] = Field(default_factory=list, max_length=MAX_LIST)
    market_context: str | None = Field(default=None, max_length=64)
    market_basis: str | None = Field(default=None, max_length=64)
    source_rank: StrictInt | None = None
    metrics: _Metrics = Field(default_factory=_Metrics)
    collected_at: str

    @field_validator("url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        return _check_url(value) if value is not None else None


class _CoverageSource(_Strict):
    source_code: str = Field(min_length=1, max_length=64)
    capability: str = Field(min_length=1, max_length=64)
    status: str = Field(min_length=1, max_length=64)
    reason: str | None = Field(default=None, max_length=256)


class _Coverage(_Strict):
    completeness: str = Field(min_length=1, max_length=64)
    sources: list[_CoverageSource] = Field(max_length=MAX_LIST)


class _Query(_Strict):
    topic: str = Field(min_length=1, max_length=MAX_TOPIC)
    markets: list[str] = Field(max_length=MAX_LIST)
    market: str | None = Field(default=None, max_length=64)
    date_from: str
    date_to: str
    sources: list[str] = Field(max_length=MAX_LIST)
    result_limit: StrictInt = Field(ge=1, le=100)
    facebook_page_id: str | None = Field(default=None, max_length=64)

    @field_validator("date_from", "date_to")
    @classmethod
    def _valid_date(cls, value: str) -> str:
        return _check_date(value)


class _Research(_Strict):
    query: _Query
    coverage: _Coverage
    executed_sources: list[str] = Field(max_length=MAX_LIST)
    status: str = Field(min_length=1, max_length=64)
    references: list[_Reference] = Field(max_length=MAX_REFERENCES)


class _Fact(_Strict):
    field: str = Field(min_length=1, max_length=64)
    value: Any


class _Observation(_Strict):
    observation_type: str = Field(min_length=1, max_length=128)
    value: Any
    evidence_fields: list[str] = Field(max_length=MAX_LIST)
    analysis_basis: str = Field(min_length=1, max_length=128)


class _Analysis(_Strict):
    reference_id: "_ReferenceId"
    facts: list[_Fact] = Field(max_length=MAX_LIST)
    observations: list[_Observation] = Field(max_length=MAX_LIST)


class _Pattern(_Strict):
    observation_type: str = Field(min_length=1, max_length=128)
    analyzed_count: StrictInt = Field(ge=0)
    matching_count: StrictInt = Field(ge=0)
    non_matching_count: StrictInt = Field(ge=0)
    ratio: float
    matching_reference_ids: list["_ReferenceId"] = Field(max_length=MAX_LIST)
    non_matching_reference_ids: list["_ReferenceId"] = Field(max_length=MAX_LIST)


class _Evidence(_Strict):
    analyses: list[_Analysis] = Field(max_length=MAX_LIST)
    patterns: list[_Pattern] = Field(max_length=MAX_LIST)


class _Provenance(_Strict):
    provider: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)


class _InterpretationItem(_Strict):
    statement: str = Field(min_length=1, max_length=MAX_STATEMENT)
    citations: list["_Citation"] = Field(max_length=MAX_LIST)


class _Interpretation(_Strict):
    model_provenance: _Provenance
    interpretations: list[_InterpretationItem] = Field(max_length=MAX_LIST)


class _Gap(_Strict):
    statement: str = Field(min_length=1, max_length=MAX_STATEMENT)
    supporting_interpretation_indexes: list[StrictInt] = Field(max_length=MAX_LIST)
    citations: list["_Citation"] = Field(max_length=MAX_LIST)


class _Opportunity(_Strict):
    statement: str = Field(min_length=1, max_length=MAX_STATEMENT)
    gap_indexes: list[StrictInt] = Field(max_length=MAX_LIST)
    citations: list["_Citation"] = Field(max_length=MAX_LIST)


class _Strategy(_Strict):
    model_provenance: _Provenance
    content_gaps: list[_Gap] = Field(max_length=MAX_LIST)
    opportunities: list[_Opportunity] = Field(max_length=MAX_LIST)


class _Idea(_Strict):
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    angle: str = Field(min_length=1, max_length=MAX_ANGLE)
    opportunity_indexes: list[StrictInt] = Field(max_length=MAX_LIST)
    citations: list["_Citation"] = Field(max_length=MAX_LIST)


class _Brief(_Strict):
    idea_index: StrictInt = Field(ge=0)
    objective: str = Field(min_length=1, max_length=MAX_ANGLE)
    format: str = Field(min_length=1, max_length=MAX_ANGLE)
    hook: str = Field(min_length=1, max_length=MAX_ANGLE)
    outline: list[str] = Field(min_length=1, max_length=MAX_OUTLINE_ITEMS)
    citations: list["_Citation"] = Field(max_length=MAX_LIST)

    @field_validator("outline")
    @classmethod
    def _outline(cls, value: list[str]) -> list[str]:
        for item in value:
            if len(item) > MAX_OUTLINE_ITEM:
                raise ValueError(
                    f"outline item is longer than {MAX_OUTLINE_ITEM} characters"
                )
        return value


class _Ideation(_Strict):
    model_provenance: _Provenance
    content_ideas: list[_Idea] = Field(max_length=MAX_LIST)
    content_briefs: list[_Brief] = Field(max_length=MAX_LIST)


class _ReferenceId(_Strict):
    source_code: str = Field(min_length=1, max_length=64)
    content_external_id: str = Field(min_length=1, max_length=256)


class _FactCitation(_Strict):
    kind: Literal["fact"]
    reference: _ReferenceId
    field: str = Field(min_length=1, max_length=64)


class _ObservationCitation(_Strict):
    kind: Literal["observation"]
    reference: _ReferenceId
    observation_type: str = Field(min_length=1, max_length=128)


class _PatternCitation(_Strict):
    kind: Literal["pattern"]
    observation_type: str = Field(min_length=1, max_length=128)


# Discriminated on ``kind``: a ``fact`` must carry a reference and a field, a
# ``pattern`` must not, so pattern-shaped fields cannot masquerade as a fact.
_Citation = Annotated[
    _FactCitation | _ObservationCitation | _PatternCitation,
    Field(discriminator="kind"),
]


class ReportSnapshot(BaseModel):
    """Strictly validated six-field report snapshot for recovery."""

    model_config = ConfigDict(extra="forbid")

    status: str
    research: _Research
    evidence: _Evidence | None
    interpretation: _Interpretation | None
    strategy: _Strategy | None
    ideation: _Ideation | None

    @field_validator("status")
    @classmethod
    def _status(cls, value: str) -> str:
        if value not in _STATUSES:
            raise ValueError("unknown report status")
        return value

    @model_validator(mode="after")
    def _relationships(self) -> "ReportSnapshot":
        _validate_relationships(self)
        return self


def _validate_citations(
    citations: list[Any],
    reference_keys: set[tuple[str, str]],
    facts_by_reference: dict[tuple[str, str], set[str]],
    observations_by_reference: dict[tuple[str, str], set[str]],
    patterns_by_type: set[str],
) -> None:
    """Resolve every citation against the snapshot's evidence.

    A citation must name an existing fact, observation, or pattern. Structural
    resolution only: it does not prove the evidence is authentic.
    """
    seen: set[tuple[Any, ...]] = set()
    for citation in citations:
        kind = citation.kind
        if kind == "pattern":
            if citation.observation_type not in patterns_by_type:
                raise ValueError("pattern citation is absent from the evidence")
            key: tuple[Any, ...] = ("pattern", citation.observation_type)
        else:
            ref = (citation.reference.source_code, citation.reference.content_external_id)
            if ref not in reference_keys:
                raise ValueError("citation references an unknown reference identity")
            if kind == "fact":
                if citation.field not in facts_by_reference.get(ref, set()):
                    raise ValueError("fact citation names a missing fact")
                key = ("fact", ref, citation.field)
            else:
                if citation.observation_type not in observations_by_reference.get(ref, set()):
                    raise ValueError("observation citation names a missing observation")
                key = ("observation", ref, citation.observation_type)
        if key in seen:
            raise ValueError("duplicate citation")
        seen.add(key)


def _validate_indexes(indexes: list[int], upper: int, label: str) -> None:
    for index in indexes:
        if index < 0 or index >= upper:
            raise ValueError(f"{label} references out-of-range index {index}")


def _validate_relationships(snapshot: ReportSnapshot) -> None:
    """Reject structurally inconsistent chain relationships."""
    reference_keys = {
        (reference.source_code, reference.content_external_id)
        for reference in snapshot.research.references
    }
    if len(reference_keys) != len(snapshot.research.references):
        raise ValueError("duplicate reference identity")

    evidence_keys: set[tuple[str, str]] = set()
    facts_by_reference: dict[tuple[str, str], set[str]] = {}
    observations_by_reference: dict[tuple[str, str], set[str]] = {}
    patterns_by_type: set[str] = set()
    if snapshot.evidence is not None:
        for analysis in snapshot.evidence.analyses:
            key = (
                analysis.reference_id.source_code,
                analysis.reference_id.content_external_id,
            )
            if key not in reference_keys:
                raise ValueError("evidence analysis references an unknown reference")
            if key in evidence_keys:
                raise ValueError("duplicate evidence analysis identity")
            evidence_keys.add(key)
            facts_by_reference[key] = {fact.field for fact in analysis.facts}
            observations_by_reference[key] = {
                observation.observation_type for observation in analysis.observations
            }
        for pattern in snapshot.evidence.patterns:
            if pattern.matching_count + pattern.non_matching_count > pattern.analyzed_count:
                raise ValueError("pattern counts exceed analyzed_count")
            if not math.isfinite(pattern.ratio):
                raise ValueError("pattern ratio must be finite")
            patterns_by_type.add(pattern.observation_type)

    interpretations = (
        snapshot.interpretation.interpretations
        if snapshot.interpretation is not None
        else []
    )
    for index, item in enumerate(interpretations):
        if not item.citations:
            raise ValueError("a finding must cite supporting evidence")
        _validate_citations(
            item.citations,
            reference_keys,
            facts_by_reference,
            observations_by_reference,
            patterns_by_type,
        )

    if snapshot.interpretation is not None and snapshot.interpretation.model_provenance.provider == "source_evidence":
        from trendora.research.reporting import source_excerpt

        if snapshot.interpretation.model_provenance.model != "extractive-v1":
            raise ValueError("unknown source-summary method")
        expected = []
        for reference in snapshot.research.references:
            for field in ("description", "title"):
                text = getattr(reference, field)
                if isinstance(text, str) and text.strip():
                    expected.append((
                        source_excerpt(text), reference.source_code, reference.content_external_id, field
                    ))
                    break
        actual = []
        for item in interpretations:
            if len(item.citations) != 1 or item.citations[0].kind != "fact":
                raise ValueError("source summary must cite one source text field")
            citation = item.citations[0]
            actual.append((item.statement, citation.reference.source_code, citation.reference.content_external_id, citation.field))
        if actual != expected:
            raise ValueError("source summaries do not match cited source excerpts")

    if snapshot.strategy is not None:
        gaps = snapshot.strategy.content_gaps
        opportunities = snapshot.strategy.opportunities
        for gap in gaps:
            _validate_citations(
                gap.citations,
                reference_keys,
                facts_by_reference,
                observations_by_reference,
                patterns_by_type,
            )
            _validate_indexes(
                gap.supporting_interpretation_indexes, len(interpretations), "gap"
            )
        for opportunity in opportunities:
            _validate_citations(
                opportunity.citations,
                reference_keys,
                facts_by_reference,
                observations_by_reference,
                patterns_by_type,
            )
            _validate_indexes(opportunity.gap_indexes, len(gaps), "opportunity")

    if snapshot.ideation is not None:
        ideas = snapshot.ideation.content_ideas
        briefs = snapshot.ideation.content_briefs
        opportunity_count = (
            len(snapshot.strategy.opportunities) if snapshot.strategy is not None else 0
        )
        for idea in ideas:
            _validate_citations(
                idea.citations,
                reference_keys,
                facts_by_reference,
                observations_by_reference,
                patterns_by_type,
            )
            _validate_indexes(idea.opportunity_indexes, opportunity_count, "idea")
        for brief in briefs:
            _validate_citations(
                brief.citations,
                reference_keys,
                facts_by_reference,
                observations_by_reference,
                patterns_by_type,
            )
            if brief.idea_index >= len(ideas):
                raise ValueError("brief references a missing parent idea")


_Analysis.model_rebuild()
_InterpretationItem.model_rebuild()
_Gap.model_rebuild()
_Opportunity.model_rebuild()
_Idea.model_rebuild()
_Brief.model_rebuild()
ReportSnapshot.model_rebuild()

__all__ = [
    "SNAPSHOT_FIELDS",
    "SCHEMA_VERSION",
    "ReportSnapshot",
    "canonical_snapshot_bytes",
    "snapshot_fingerprint",
]
