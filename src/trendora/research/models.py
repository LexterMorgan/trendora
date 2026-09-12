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
    from trendora.research.retrieval import ResearchRetriever
    from trendora.research.service import ResearchCapabilityResolver

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


def _normalize_markets(markets: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for market in markets:
        text = market.strip().upper()
        if not text:
            raise ResearchValidationError("markets must not contain blank entries")
        if text not in MARKET_CODES:
            raise ResearchValidationError(
                f"unsupported market {text!r}; supported: {sorted(MARKET_CODES)}"
            )
        if text not in normalized:
            normalized.append(text)
    return tuple(normalized)


@dataclass(frozen=True, kw_only=True)
class ResearchQuery:
    """A validated, structured research request (docs/14 section 7).

    ``markets`` is the canonical ordered, normalized, deduplicated market list
    (M26C). ``market`` is the legacy singular field: the sole market for
    single-market requests, ``None`` otherwise. ``facebook_page_id`` is the
    explicit single Facebook Page target (M25C); ``topic`` and ``markets``
    remain part of the shared contract but do not filter or alter Facebook
    collection. Values are normalized at construction and validated so an
    invalid query cannot be constructed.
    """

    topic: str
    date_from: date
    date_to: date
    markets: tuple[str, ...] = ()
    source_codes: tuple[str, ...] = DEFAULT_SOURCE_CODES
    result_limit: int = DEFAULT_RESULT_LIMIT
    facebook_page_id: str | None = None
    market: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "topic", self.topic.strip())
        resolved = self.markets
        if not resolved and self.market is not None:
            resolved = (self.market,)
        object.__setattr__(self, "markets", _normalize_markets(resolved))
        # Legacy singular field: the sole market for single-market requests,
        # None for multi-market runs. Derived when not explicitly provided.
        if self.market is None and len(self.markets) == 1:
            object.__setattr__(self, "market", self.markets[0])
        else:
            object.__setattr__(
                self, "market", self.market.strip().upper() if self.market is not None else None
            )
        object.__setattr__(self, "source_codes", _normalize_source_codes(self.source_codes))
        object.__setattr__(self, "facebook_page_id", _normalize_facebook_page_id(self.facebook_page_id))
        validate_research_query(self)


def _normalize_facebook_page_id(value: str | None) -> str | None:
    if value is None:
        return None
    from trendora.connectors.facebook.identity import normalize_page_id

    try:
        return normalize_page_id(value)
    except ValueError:
        raise ResearchValidationError(
            "facebook_page_id must be a safe identifier"
        ) from None


def validate_research_query(query: ResearchQuery) -> None:
    """Deterministic ResearchQuery validation. Raises ResearchValidationError."""
    if not query.topic:
        raise ResearchValidationError("topic must not be blank")
    if not query.markets:
        raise ResearchValidationError("at least one market is required")
    for market in query.markets:
        if market not in MARKET_CODES:
            raise ResearchValidationError(
                f"unsupported market {market!r}; supported: {sorted(MARKET_CODES)}"
            )
    if query.date_from > query.date_to:
        raise ResearchValidationError("date_from must not be after date_to")
    if not query.source_codes:
        raise ResearchValidationError("at least one source code is required")
    if not 1 <= query.result_limit <= MAX_RESULT_LIMIT:
        raise ResearchValidationError(
            f"result_limit must be between 1 and {MAX_RESULT_LIMIT}"
        )
    page_id = query.facebook_page_id
    if "facebook" in query.source_codes and not page_id:
        raise ResearchValidationError(
            "facebook research requires a nonblank facebook_page_id"
        )
    if page_id is not None and "facebook" not in query.source_codes:
        raise ResearchValidationError(
            "facebook_page_id requires the facebook source to be requested"
        )


def allocate_result_limits(
    result_limit: int, source_codes: tuple[str, ...]
) -> tuple[tuple[str, int], ...]:
    """Deterministically split a global ``result_limit`` across sources.

    Uses ``divmod``: every executable source receives an even base share, and
    earlier requested sources receive any remainder first. A single-source
    request receives the full limit. The shares always sum to exactly
    ``result_limit``. Raises ``ResearchValidationError`` when the limit is
    below the executable source count (a source cannot receive zero).
    """
    count = len(source_codes)
    if count == 0:
        return ()
    base, remainder = divmod(result_limit, count)
    if base == 0:
        raise ResearchValidationError(
            f"result_limit must be at least the number of executable sources ({count})"
        )
    return tuple(
        (source_code, base + 1 if index < remainder else base)
        for index, source_code in enumerate(source_codes)
    )


def _merge_targets(
    collected_batches: "tuple[tuple[ResearchRetriever, ResearchQuery, object], ...]",
) -> list["ResearchReference"]:
    """Cap, merge, dedupe, and re-rank normalized references across targets.

    Deterministic target order. Each target is capped at its allocated
    ``result_limit``. Deduplication is by ``(source_code,
    content_external_id)`` with the first occurrence owning all source facts;
    duplicate YouTube videos union ``market_contexts`` in selected-market
    order. ``source_rank`` is reassigned per source after deduplication using
    first-seen merged order. Metrics are never combined.
    """
    merged: list[ResearchReference] = []
    seen: dict[tuple[str, str], ResearchReference] = {}
    for retriever, source_query, collected in collected_batches:
        for reference in retriever.normalize(collected)[: source_query.result_limit]:
            key = (reference.source_code, reference.content_external_id)
            existing = seen.get(key)
            if existing is None:
                seen[key] = reference
                merged.append(reference)
            elif existing.market_contexts and reference.market_contexts:
                # Union market contexts in selected-market order, keeping the
                # first occurrence's other source facts untouched.
                union: list[str] = list(existing.market_contexts)
                for market in reference.market_contexts:
                    if market not in union:
                        union.append(market)
                object.__setattr__(existing, "market_contexts", tuple(union))
    _reassign_source_ranks(merged)
    _sync_legacy_market_context(merged)
    return merged


def _sync_legacy_market_context(references: list["ResearchReference"]) -> None:
    """Keep ``market_context`` truthful: sole context, or ``None`` otherwise."""
    for reference in references:
        contexts = reference.market_contexts
        object.__setattr__(
            reference,
            "market_context",
            contexts[0] if len(contexts) == 1 else None,
        )


def _reassign_source_ranks(references: list["ResearchReference"]) -> None:
    """Reassign 1-based source-local ranks by first-seen merged order."""
    counts: dict[str, int] = {}
    for reference in references:
        rank = counts.get(reference.source_code, 0) + 1
        counts[reference.source_code] = rank
        object.__setattr__(reference, "source_rank", rank)


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
    """Immutable raw source statistics (M14 + M25B).

    Official source facts only: ``view_count``/``like_count`` are YouTube-only;
    ``comment_count`` applies to both YouTube and Facebook; ``reaction_count``/
    ``share_count`` are Facebook-only. A missing statistic is ``None`` (never
    zero; zero is distinct from missing). Reactions are reactions, never likes.
    No derived metrics and no generic metric bag: the set of fields is fixed
    and cannot be mutated.
    """

    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    reaction_count: int | None = None
    share_count: int | None = None


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

    ``market_contexts`` is the canonical ordered list of selected markets in
    which this reference was returned (M26C); ``market_context`` is the legacy
    singular field — the sole context when exactly one exists, ``None``
    otherwise. ``market_basis`` states exactly what these markets mean for this
    source. For YouTube it is ``youtube_region_availability``: regionCode
    reflects regional availability/viewability, NOT creator/publisher/content
    origin country and NOT language. Facebook keeps empty ``market_contexts``
    because topic/market do not filter Page-post collection. No
    country-of-origin field is ever inferred.

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
    market_contexts: tuple[str, ...] = ()
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

    def execute(self, source_code: str, retriever: ResearchRetriever) -> None:
        """Execute retrieval for one source on a READY run.

        Records ``source_code`` as attempted before collection, so execution
        provenance is truthful even on failure. On failure the run is marked
        FAILED and the original error is re-raised so callers can handle it.
        """
        self.execute_sources(((source_code, self._query, retriever),))

    def execute_sources(
        self,
        entries: "tuple[tuple[str, ResearchQuery, ResearchRetriever], ...]",
    ) -> None:
        """Execute a multi-target retrieval plan on a READY run.

        Each entry is one retrieval target: YouTube produces one target per
        selected market; Facebook produces exactly one target regardless of
        market count. Every planned retriever is called exactly once, in the
        given order: all ``collect`` calls run while the run is COLLECTING,
        then the run transitions to NORMALIZING before the first ``normalize``
        call.

        Merge is deterministic: each target's normalized references are capped
        at its allocated ``result_limit``, merged in target order, then
        deduplicated by ``(source_code, content_external_id)``. The first
        occurrence owns all source facts; for duplicate YouTube videos the
        ``market_contexts`` are unioned in selected-market order. Metrics are
        never summed or combined. ``source_rank`` is reassigned per source
        after deduplication using first-seen merged order (source order only,
        not a relevance/performance ranking).

        ``executed_sources`` records unique source codes actually attempted, in
        first-attempt order, including a failing source. An empty plan is
        rejected before any state change. On any collection or normalization
        failure the run is marked FAILED and the original error is re-raised —
        never a silent partial success.
        """
        if not entries:
            from trendora.research.exceptions import ResearchStateError

            raise ResearchStateError("execution plan must contain at least one source")
        self._transition(ResearchRunStatus.COLLECTING)
        executed: list[str] = []
        collected_batches: list[tuple[ResearchRetriever, ResearchQuery, object]] = []
        try:
            # Collection phase: every target's collect runs while COLLECTING.
            for source_code, source_query, retriever in entries:
                if source_code not in executed:
                    executed.append(source_code)
                self._executed_sources = tuple(executed)
                collected_batches.append(
                    (retriever, source_query, retriever.collect(source_query))
                )
            self._transition(ResearchRunStatus.NORMALIZING)
            references: list[ResearchReference] = _merge_targets(collected_batches)
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
