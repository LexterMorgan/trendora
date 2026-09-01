"""Research domain models (M13).

Deterministic, in-memory contracts for the research core:
- ``PlatformCapability`` / ``SourceCapabilities``: what a source CAN support.
- ``ResearchQuery``: a validated, structured research request.
- ``SourceCoverage`` / ``CoverageCompleteness`` / ``ResearchCoverage``: the
  truthful result of resolving a query against capability declarations.
- ``ResearchRun`` / ``ResearchRunStatus``: the synchronous run lifecycle.

Nothing here queries a database, calls a network, or touches connectors.
Persistence and retrieval are deliberately deferred to M14+.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from trendora.reference import MARKET_IDS
from trendora.research.exceptions import ResearchValidationError

if TYPE_CHECKING:
    from trendora.research.service import ResearchCapabilityResolver
    from trendora.research.youtube import YouTubeResearchRetriever

MAX_RESULT_LIMIT: Final[int] = 100
DEFAULT_SOURCE_CODES: Final[tuple[str, ...]] = ("youtube",)
DEFAULT_RESULT_LIMIT: Final[int] = 50

MARKET_CODES: Final[frozenset[str]] = frozenset(MARKET_IDS)


class PlatformCapability(StrEnum):
    """What a platform can support (docs/14 section 9).

    Capability is distinct from credentials, authorization state, temporary
    API errors, policy constraints, and whether a query requested it.
    """

    PUBLIC_SEARCH = "public_search"
    CREATOR_WATCHLIST = "creator_watchlist"
    CONTENT_LOOKUP = "content_lookup"
    HASHTAG_DISCOVERY = "hashtag_discovery"
    PUBLIC_METRICS = "public_metrics"
    OWNED_ACCOUNT_METRICS = "owned_account_metrics"
    REGIONAL_DISCOVERY = "regional_discovery"
    CONTENT_TEXT_AVAILABLE = "content_text_available"
    MEDIA_ANALYSIS_AVAILABLE = "media_analysis_available"


@dataclass(frozen=True, kw_only=True)
class SourceCapabilities:
    """A source's declared capability set. Static and immutable.

    ``supported`` is what the platform can do today without authorization.
    ``conditional`` is what the platform can do only under a condition, such
    as channel-owner OAuth. Authorization is **capability-specific**: a source
    may support ``public_search`` without authorization while an
    ``owned_account_metrics`` capability sits in ``conditional``. There is
    intentionally no source-wide ``requires_authorization`` boolean, because
    it would misstate mixed-access sources. A capability must appear in
    exactly one of the two sets to keep resolution unambiguous.
    """

    source_code: str
    supported: frozenset[PlatformCapability]
    conditional: frozenset[PlatformCapability] = frozenset()
    retention_note: str | None = None

    def __post_init__(self) -> None:
        overlap = self.supported & self.conditional
        if overlap:
            raise ValueError(
                f"capability {sorted(overlap)} declared both supported and conditional"
            )


def _normalize_source_codes(codes: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for code in codes:
        text = code.strip().lower()
        if not text:
            raise ResearchValidationError("source codes must not be blank")
        if text not in normalized:
            normalized.append(text)
    return tuple(normalized)


@dataclass(frozen=True, kw_only=True)
class ResearchQuery:
    """A validated, structured research request (docs/14 section 7).

    V1 is intentionally narrow: topic + market + date window + requested
    sources + result limit. Values are normalized at construction (topic is
    trimmed, market uppercased, source codes lowercased/deduplicated) and
    validated, so an invalid query cannot be constructed.
    """

    topic: str
    market: str
    date_from: date
    date_to: date
    source_codes: tuple[str, ...] = DEFAULT_SOURCE_CODES
    result_limit: int = DEFAULT_RESULT_LIMIT

    def __post_init__(self) -> None:
        object.__setattr__(self, "topic", self.topic.strip())
        object.__setattr__(self, "market", self.market.strip().upper())
        object.__setattr__(self, "source_codes", _normalize_source_codes(self.source_codes))
        validate_research_query(self)


def validate_research_query(query: ResearchQuery) -> None:
    """Deterministic ResearchQuery validation. Raises ResearchValidationError."""
    if not query.topic:
        raise ResearchValidationError("topic must not be blank")
    if query.market not in MARKET_CODES:
        raise ResearchValidationError(
            f"unsupported market {query.market!r}; supported: {sorted(MARKET_CODES)}"
        )
    if query.date_from > query.date_to:
        raise ResearchValidationError("date_from must not be after date_to")
    if not query.source_codes:
        raise ResearchValidationError("at least one source code is required")
    if not 1 <= query.result_limit <= MAX_RESULT_LIMIT:
        raise ResearchValidationError(
            f"result_limit must be between 1 and {MAX_RESULT_LIMIT}"
        )


class CoverageStatus(StrEnum):
    """Per-(source, capability) resolution outcome."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    CONDITIONAL = "conditional"


class CoverageReason(StrEnum):
    """Machine-readable reason for a non-available coverage result."""

    SOURCE_UNKNOWN = "source_unknown"
    CAPABILITY_NOT_SUPPORTED = "capability_not_supported"
    AUTHORIZATION_REQUIRED = "authorization_required"


class MarketBasis(StrEnum):
    """What a reference's ``market_context`` actually means.

    For YouTube, ``regionCode`` selects content available/viewable in a
    region. It is NOT creator nationality, publisher nationality, or
    content country-of-origin evidence, and it says nothing about language.
    """

    YOUTUBE_REGION_AVAILABILITY = "youtube_region_availability"


@dataclass(frozen=True, kw_only=True)
class SourceCoverage:
    """Resolution of one requested source for one required capability."""

    source_code: str
    capability: PlatformCapability
    status: CoverageStatus
    reason: CoverageReason | None = None


class CoverageCompleteness(StrEnum):
    """Coverage completeness of a research query (docs/14 section 20).

    This is coverage truth, not a quality/confidence score.
    """

    COMPLETE = "complete"
    PARTIAL = "partial"
    NONE = "none"


@dataclass(frozen=True, kw_only=True)
class ResearchCoverage:
    """Coverage result for a query: per-source facts + completeness."""

    sources: tuple[SourceCoverage, ...]
    completeness: CoverageCompleteness


@dataclass(frozen=True, slots=True)
class ResearchMetrics:
    """Immutable raw YouTube video statistics (M14).

    Exactly three official source facts: ``view_count``, ``like_count``,
    ``comment_count``. A missing statistic is ``None`` (never zero; zero is
    distinct from missing). No derived metrics and no generic metric bag:
    the set of fields is fixed and cannot be mutated after construction.
    """

    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None


@dataclass(frozen=True, kw_only=True)
class ResearchReference:
    """One normalized in-memory research reference (M14).

    Carries official source facts only: metadata plus public statistics
    (``ResearchMetrics``). Missing raw metrics are explicit ``None``, never
    zero. No derived metrics, no scores, no Trendora-derived claims. All
    fields are immutable after construction.

    ``description`` is YouTube source metadata (search/video snippet). It is
    NOT a transcript, caption, or analysis of the video content, and it must
    never be presented as such.

    ``market_context`` is the requested market code (e.g. ``"SG"``);
    ``market_basis`` states exactly what that market means for this source.
    For YouTube it is ``youtube_region_availability``: regionCode reflects
    regional availability/viewability, NOT creator/publisher/content origin
    country and NOT language. No country-of-origin field is ever inferred.

    ``source_rank`` is the 1-based position of the video in the deduplicated
    source search order. It is source order only, not a relevance,
    performance, confidence, or opportunity score.
    """

    source_code: str
    content_external_id: str
    collected_at: datetime
    url: str | None = None
    title: str | None = None
    description: str | None = None
    published_at: datetime | None = None
    channel_external_id: str | None = None
    channel_title: str | None = None
    market_context: str | None = None
    market_basis: MarketBasis | None = None
    source_rank: int | None = None
    metrics: ResearchMetrics = field(default_factory=ResearchMetrics)


class ResearchRunStatus(StrEnum):
    """Execution status of a research run.

    M13 resolves capabilities; M14 extends READY into real retrieval
    execution. READY means at least one requested source can satisfy the
    required capability and the run is eligible for collection. BLOCKED means
    no requested source can satisfy it. COLLECTING / NORMALIZING / COMPLETED /
    FAILED describe actual retrieval execution. Capability resolution success
    is not research execution completion: a run must pass through collection
    and normalization before it is COMPLETED.
    """

    REQUESTED = "requested"
    RESOLVING_CAPABILITIES = "resolving_capabilities"
    READY = "ready"
    BLOCKED = "blocked"
    COLLECTING = "collecting"
    NORMALIZING = "normalizing"
    COMPLETED = "completed"
    FAILED = "failed"


_TRANSITIONS: dict[ResearchRunStatus, frozenset[ResearchRunStatus]] = {
    ResearchRunStatus.REQUESTED: frozenset({ResearchRunStatus.RESOLVING_CAPABILITIES}),
    ResearchRunStatus.RESOLVING_CAPABILITIES: frozenset(
        {ResearchRunStatus.READY, ResearchRunStatus.BLOCKED}
    ),
    ResearchRunStatus.READY: frozenset({ResearchRunStatus.COLLECTING}),
    ResearchRunStatus.COLLECTING: frozenset(
        {ResearchRunStatus.NORMALIZING, ResearchRunStatus.FAILED}
    ),
    ResearchRunStatus.NORMALIZING: frozenset(
        {ResearchRunStatus.COMPLETED, ResearchRunStatus.FAILED}
    ),
}


def _terminal_status(completeness: CoverageCompleteness) -> ResearchRunStatus:
    if completeness is CoverageCompleteness.NONE:
        return ResearchRunStatus.BLOCKED
    return ResearchRunStatus.READY


class ResearchRun:
    """Synchronous in-memory research run lifecycle.

    M13: ``resolve_capabilities`` resolves source coverage into READY or
    BLOCKED. M14: ``execute`` runs real retrieval (collection + normalization)
    on a READY run, ending in COMPLETED with references, or FAILED. Execution
    status, coverage completeness, and executed sources are separate concepts:
    a run records exactly which source(s) it attempted regardless of what was
    requested or what coverage declared.
    """

    def __init__(self, query: ResearchQuery) -> None:
        self._query = query
        self._status = ResearchRunStatus.REQUESTED
        self._coverage: ResearchCoverage | None = None
        self._references: tuple[ResearchReference, ...] | None = None
        self._executed_sources: tuple[str, ...] = ()

    @property
    def query(self) -> ResearchQuery:
        return self._query

    @property
    def status(self) -> ResearchRunStatus:
        return self._status

    @property
    def coverage(self) -> ResearchCoverage | None:
        return self._coverage

    @property
    def references(self) -> tuple[ResearchReference, ...] | None:
        return self._references

    @property
    def executed_sources(self) -> tuple[str, ...]:
        """Source codes Trendora actually attempted (empty before execution).

        ``executed_sources`` is execution truth, distinct from requested
        sources and from capability coverage. It stays populated even when a
        successful search returns zero references.
        """
        return self._executed_sources

    def resolve_capabilities(self, resolver: ResearchCapabilityResolver) -> None:
        """Resolve source coverage, then move to the matching terminal state."""
        self._transition(ResearchRunStatus.RESOLVING_CAPABILITIES)
        coverage = resolver.resolve(self._query)
        self._coverage = coverage
        self._transition(_terminal_status(coverage.completeness))

    def execute(self, source_code: str, retriever: YouTubeResearchRetriever) -> None:
        """Execute retrieval for one source on a READY run.

        Records ``source_code`` as attempted before collection, so execution
        provenance is truthful even on failure. On failure the run is marked
        FAILED and the original error is re-raised so callers can handle it.
        """
        self._transition(ResearchRunStatus.COLLECTING)
        self._executed_sources = (source_code,)
        try:
            collected = retriever.collect(self._query)
            self._transition(ResearchRunStatus.NORMALIZING)
            references = retriever.normalize(collected)
            self._references = tuple(references)
            self._transition(ResearchRunStatus.COMPLETED)
        except Exception:
            self._transition(ResearchRunStatus.FAILED)
            raise

    def _transition(self, target: ResearchRunStatus) -> None:
        from trendora.research.exceptions import ResearchStateError

        allowed = _TRANSITIONS.get(self._status, frozenset())
        if target not in allowed:
            raise ResearchStateError(f"invalid transition {self._status.value} -> {target.value}")
        self._status = target
