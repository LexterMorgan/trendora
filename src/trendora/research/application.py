"""Research application service (M15).

Thin synchronous orchestration over the M13/M14 research domain. It is the
single application entry point the HTTP adapter calls.

Flow:
    validated inputs
      → construct/validate ResearchQuery
      → resolve capability coverage
      → create ResearchRun (READY | BLOCKED)
      → execute every available requested source in normalized request order
        (each with its own source-specific query and allocated limit; M26B
        combined YouTube + Facebook execution)
      → return the ResearchRun

Explicit and small: no command bus, workflow engine, event bus, plugin
framework, or DI container. Static capability truth and runtime retriever
availability are separate: an available source without a registered retriever
raises ``ResearchSourceNotConfiguredError``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from trendora.connectors.facebook.client import FacebookPublicClient
from trendora.connectors.web_search.serper_gateway import SerperGateway
from trendora.connectors.youtube.client import YouTubeClient
from trendora.research.exceptions import (
    ResearchSourceNotConfiguredError,
    ResearchValidationError,
)
from trendora.research.models import (
    CoverageStatus,
    ResearchCoverage,
    ResearchQuery,
    ResearchRun,
    ResearchRunStatus,
    SourceCoverage,
)
from trendora.research.facebook import FacebookResearchRetriever
from trendora.research.retrieval import ResearchRetriever
from trendora.research.service import ResearchCapabilityResolver
from trendora.research.web_search import WebSearchResearchRetriever
from trendora.research.youtube import YouTubeResearchRetriever


def build_research_application_service(
    *,
    youtube_client: YouTubeClient | None,
    facebook_client: FacebookPublicClient | None = None,
    serp_gateway: SerperGateway | None = None,
    resolver: ResearchCapabilityResolver | None = None,
) -> ResearchApplicationService:
    """Build the application service with the runtime retrievers that exist.

    ``youtube_client`` / ``facebook_client`` / ``serp_gateway`` are
    already-configured clients (or ``None`` when unavailable). Static capability
    truth is unchanged by runtime configuration: a statically-available source
    without a registered retriever raises ``ResearchSourceNotConfiguredError``
    when requested.
    """
    retrievers: dict[str, ResearchRetriever] = {}
    if youtube_client is not None:
        retrievers["youtube"] = YouTubeResearchRetriever(youtube_client)
    if facebook_client is not None:
        retrievers["facebook"] = FacebookResearchRetriever(facebook_client)
    if serp_gateway is not None:
        retrievers["public_web"] = WebSearchResearchRetriever(serp_gateway)
    return ResearchApplicationService(
        resolver=resolver or ResearchCapabilityResolver(),
        retrievers=retrievers,
    )


class ResearchApplicationService:
    """Executes one synchronous research request and returns the run."""

    def __init__(
        self,
        resolver: ResearchCapabilityResolver,
        retrievers: Mapping[str, ResearchRetriever],
    ) -> None:
        self._resolver = resolver
        self._retrievers = dict(retrievers)

    def execute(
        self,
        *,
        topic: str,
        market: str | None = None,
        markets: Sequence[str] | None = None,
        date_from: date,
        date_to: date,
        sources: Sequence[str],
        result_limit: int,
        facebook_page_id: str | None = None,
    ) -> ResearchRun:
        """Run research for a request and return the completed/blocked run.

        Accepts either legacy singular ``market`` or plural ``markets``. Domain
        validation happens inside ``ResearchQuery`` construction; the HTTP
        adapter never duplicates it.
        """
        query = ResearchQuery(
            topic=topic,
            markets=_resolve_markets(market, markets),
            market=market,
            date_from=date_from,
            date_to=date_to,
            source_codes=tuple(sources),
            result_limit=result_limit,
            facebook_page_id=facebook_page_id,
        )
        run = ResearchRun(query)
        run.resolve_capabilities(self._resolver)
        if run.status is not ResearchRunStatus.READY:
            return run
        self._execute_available(run)
        return run

    def _execute_available(self, run: ResearchRun) -> None:
        """Build and execute the multi-target plan for a READY run.

        The plan contains one retrieval target per selected market for every
        available YouTube source, plus exactly one Facebook target regardless
        of market count, in normalized request order. Before any network call,
        every planned source must have a configured retriever — one missing
        retriever fails the whole request with the sanitized
        ``ResearchSourceNotConfiguredError`` and zero retrieval calls. The
        global ``result_limit`` is split deterministically across targets
        (``divmod``; earlier targets take any remainder), and each retriever
        receives its own target-specific validated query.
        """
        coverage = run.coverage
        assert coverage is not None
        query = run.query
        targets: list[tuple[str, ResearchRetriever, str | None]] = []
        for source_code in query.source_codes:
            item = _source_coverage(coverage, source_code)
            if item is None or item.status is not CoverageStatus.AVAILABLE:
                continue
            retriever = self._retrievers.get(source_code)
            if retriever is None:
                raise ResearchSourceNotConfiguredError(
                    "no requested available source has a configured runtime retriever"
                )
            if source_code == "facebook":
                targets.append((source_code, retriever, None))
            elif source_code == "public_web":
                # Web search is not market-filtered: one target regardless of
                # market count, with the selected markets as report context.
                targets.append((source_code, retriever, None))
            else:
                for market in query.markets:
                    targets.append((source_code, retriever, market))
        if not targets:
            raise ResearchSourceNotConfiguredError(
                "no requested available source has a configured runtime retriever"
            )
        if query.result_limit < len(targets):
            raise ResearchValidationError(
                f"result_limit must be at least the number of retrieval targets ({len(targets)})"
            )
        limits = _allocate_target_limits(query.result_limit, len(targets))
        entries = tuple(
            (source_code, _target_query(query, source_code, market, limit), retriever)
            for (source_code, retriever, market), limit in zip(targets, limits, strict=True)
        )
        run.execute_sources(entries)


def _source_coverage(coverage: ResearchCoverage, source_code: str) -> SourceCoverage | None:
    for item in coverage.sources:
        if item.source_code == source_code:
            return item
    return None


def _resolve_markets(
    market: str | None, markets: Sequence[str] | None
) -> tuple[str, ...]:
    """Resolve singular/plural market inputs into the canonical market tuple.

    Exactly one of ``market`` / ``markets`` must be supplied. The canonical
    normalized/deduplicated/validated form is produced by ``ResearchQuery``.
    """
    if market is not None and markets is not None:
        raise ResearchValidationError(
            "provide either 'market' or 'markets', not both"
        )
    if market is not None:
        return (market,)
    if markets is not None:
        return tuple(markets)
    raise ResearchValidationError("at least one market is required")


def _allocate_target_limits(result_limit: int, target_count: int) -> tuple[int, ...]:
    """Deterministically split the global limit across retrieval targets.

    ``divmod``: even base share per target, earlier targets take any remainder.
    """
    base, remainder = divmod(result_limit, target_count)
    return tuple(base + 1 if index < remainder else base for index in range(target_count))


def _target_query(
    query: ResearchQuery, source_code: str, market: str | None, limit: int
) -> ResearchQuery:
    """A validated per-target query: one market, own source code, allocated limit.

    YouTube gets one market per target; Facebook gets all selected markets as
    report context but does not filter using them. Facebook keeps
    ``facebook_page_id``; non-Facebook queries never carry one.
    """
    markets = query.markets if source_code == "facebook" else ((market,) if market is not None else query.markets)
    return ResearchQuery(
        topic=query.topic,
        markets=markets,
        market=market,
        date_from=query.date_from,
        date_to=query.date_to,
        source_codes=(source_code,),
        result_limit=limit,
        facebook_page_id=query.facebook_page_id if source_code == "facebook" else None,
    )
