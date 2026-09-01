"""Deterministic per-reference evidence facts and content observations (M17).

Turns one in-memory ``ResearchReference`` into:
- ``EvidenceFact``: a source value directly present in the reference (FACT).
- ``ContentObservation``: a deterministic structural statement derived from
  specific source fields (OBSERVATION).

No AI, no aggregation, no performance judgments, no derived metrics. Every
observation cites exactly which ``EvidenceField``(s) and ``AnalysisBasis``
support it. All outputs are immutable and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import re

from trendora.research.models import (
    MarketBasis,
    ResearchMetrics,
    ResearchReference,
)

_HTTP_URL_RE = re.compile(r"https?://", re.IGNORECASE)


class ClaimType(StrEnum):
    """Claim categories M17 may emit. AI/recommendation types come later."""

    FACT = "fact"
    OBSERVATION = "observation"


class EvidenceField(StrEnum):
    """Source fields that can act as evidence.

    Identity fields (``source_code``, ``content_external_id``) live on
    ``ReferenceId``, not here. ``collected_at`` is temporal provenance: the
    timezone-aware time Trendora retrieved the source data, preserved exactly
    from ``ResearchReference.collected_at``. No transcript/video/audio/visual
    fields exist because M14 does not provide those facts.
    """

    URL = "url"
    COLLECTED_AT = "collected_at"
    TITLE = "title"
    DESCRIPTION = "description"
    PUBLISHED_AT = "published_at"
    CHANNEL_TITLE = "channel_title"
    MARKET_CONTEXT = "market_context"
    MARKET_BASIS = "market_basis"
    SOURCE_RANK = "source_rank"
    VIEW_COUNT = "view_count"
    LIKE_COUNT = "like_count"
    COMMENT_COUNT = "comment_count"


class AnalysisBasis(StrEnum):
    """What source material the analyzer actually possessed.

    No TRANSCRIPT/AUDIO/VIDEO/IMAGE/CAPTION: M14 does not provide them.
    """

    TITLE = "title"
    DESCRIPTION = "description"
    SOURCE_METADATA = "source_metadata"
    RAW_METRICS = "raw_metrics"


class ObservationType(StrEnum):
    """Objectively detectable structural properties of source metadata only."""

    TITLE_CHARACTER_COUNT = "title_character_count"
    TITLE_HAS_NUMERAL = "title_has_numeral"
    TITLE_HAS_QUESTION_MARK = "title_has_question_mark"
    DESCRIPTION_PRESENT = "description_present"
    DESCRIPTION_CHARACTER_COUNT = "description_character_count"
    DESCRIPTION_HAS_URL = "description_has_url"


FactValue = str | int | datetime | None
ObservationValue = bool | int


@dataclass(frozen=True, slots=True)
class ReferenceId:
    """Smallest immutable identity of the ResearchReference that produced output."""

    source_code: str
    content_external_id: str


@dataclass(frozen=True, slots=True)
class EvidenceFact:
    """A source value directly present in the ResearchReference.

    ``claim_type`` is always FACT and cannot be set by callers (structural
    invariant: an EvidenceFact cannot be constructed as an observation).
    """

    reference: ReferenceId
    field: EvidenceField
    value: FactValue
    claim_type: ClaimType = field(default=ClaimType.FACT, init=False)


@dataclass(frozen=True, slots=True)
class ContentObservation:
    """A deterministic structural statement derived from specific evidence fields.

    ``claim_type`` is always OBSERVATION and cannot be set by callers
    (structural invariant: an observation cannot be constructed as a fact).
    """

    reference: ReferenceId
    observation_type: ObservationType
    value: ObservationValue
    evidence_fields: tuple[EvidenceField, ...]
    analysis_basis: AnalysisBasis
    claim_type: ClaimType = field(default=ClaimType.OBSERVATION, init=False)


@dataclass(frozen=True, slots=True)
class ReferenceAnalysis:
    """Immutable per-reference analysis: identity, basis used, facts, observations."""

    reference: ReferenceId
    analysis_basis: tuple[AnalysisBasis, ...]
    facts: tuple[EvidenceFact, ...]
    observations: tuple[ContentObservation, ...]


def reference_id(reference: ResearchReference) -> ReferenceId:
    return ReferenceId(
        source_code=reference.source_code,
        content_external_id=reference.content_external_id,
    )


def extract_evidence(reference: ResearchReference) -> tuple[EvidenceFact, ...]:
    """Convert a reference into source ``EvidenceFact`` objects (deterministic order).

    Missing source values stay ``None``; zero stays zero; integer metrics are
    never converted to strings.
    """
    identity = reference_id(reference)
    metrics = reference.metrics
    return (
        EvidenceFact(identity, EvidenceField.URL, reference.url),
        EvidenceFact(identity, EvidenceField.COLLECTED_AT, reference.collected_at),
        EvidenceFact(identity, EvidenceField.TITLE, reference.title),
        EvidenceFact(identity, EvidenceField.DESCRIPTION, reference.description),
        EvidenceFact(identity, EvidenceField.PUBLISHED_AT, reference.published_at),
        EvidenceFact(identity, EvidenceField.CHANNEL_TITLE, reference.channel_title),
        EvidenceFact(identity, EvidenceField.MARKET_CONTEXT, reference.market_context),
        EvidenceFact(
            identity,
            EvidenceField.MARKET_BASIS,
            reference.market_basis.value if reference.market_basis is not None else None,
        ),
        EvidenceFact(identity, EvidenceField.SOURCE_RANK, reference.source_rank),
        EvidenceFact(identity, EvidenceField.VIEW_COUNT, metrics.view_count),
        EvidenceFact(identity, EvidenceField.LIKE_COUNT, metrics.like_count),
        EvidenceFact(identity, EvidenceField.COMMENT_COUNT, metrics.comment_count),
    )


def analyze_reference(reference: ResearchReference) -> ReferenceAnalysis:
    """Deterministically analyze one reference. Never mutates the reference."""
    identity = reference_id(reference)
    facts = extract_evidence(reference)
    observations = tuple(_observations(reference, identity))
    return ReferenceAnalysis(
        reference=identity,
        analysis_basis=_basis_used(observations),
        facts=facts,
        observations=observations,
    )


def analyze_references(references) -> tuple[ReferenceAnalysis, ...]:
    """Analyze each reference independently. No cross-reference aggregation."""
    return tuple(analyze_reference(reference) for reference in references)


def _observations(reference: ResearchReference, identity: ReferenceId) -> list[ContentObservation]:
    title = reference.title or ""
    description = reference.description or ""
    description_present = bool(reference.description and reference.description.strip())
    return [
        ContentObservation(
            reference=identity,
            observation_type=ObservationType.TITLE_CHARACTER_COUNT,
            value=len(title),
            evidence_fields=(EvidenceField.TITLE,),
            analysis_basis=AnalysisBasis.TITLE,
        ),
        ContentObservation(
            reference=identity,
            observation_type=ObservationType.TITLE_HAS_NUMERAL,
            value=any(char.isdigit() for char in title),
            evidence_fields=(EvidenceField.TITLE,),
            analysis_basis=AnalysisBasis.TITLE,
        ),
        ContentObservation(
            reference=identity,
            observation_type=ObservationType.TITLE_HAS_QUESTION_MARK,
            value=("?" in title) or ("？" in title),
            evidence_fields=(EvidenceField.TITLE,),
            analysis_basis=AnalysisBasis.TITLE,
        ),
        ContentObservation(
            reference=identity,
            observation_type=ObservationType.DESCRIPTION_PRESENT,
            value=description_present,
            evidence_fields=(EvidenceField.DESCRIPTION,),
            analysis_basis=AnalysisBasis.DESCRIPTION,
        ),
        ContentObservation(
            reference=identity,
            observation_type=ObservationType.DESCRIPTION_CHARACTER_COUNT,
            value=len(description),
            evidence_fields=(EvidenceField.DESCRIPTION,),
            analysis_basis=AnalysisBasis.DESCRIPTION,
        ),
        ContentObservation(
            reference=identity,
            observation_type=ObservationType.DESCRIPTION_HAS_URL,
            value=_HTTP_URL_RE.search(description) is not None,
            evidence_fields=(EvidenceField.DESCRIPTION,),
            analysis_basis=AnalysisBasis.DESCRIPTION,
        ),
    ]


def _basis_used(observations: tuple[ContentObservation, ...]) -> tuple[AnalysisBasis, ...]:
    seen: list[AnalysisBasis] = []
    for observation in observations:
        if observation.analysis_basis not in seen:
            seen.append(observation.analysis_basis)
    return tuple(seen)
