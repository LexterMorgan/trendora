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
from trendora.connectors.youtube.client import YouTubeClient
from trendora.research.exceptions import ResearchSourceNotConfiguredError
from trendora.research.models import (
    CoverageStatus,
    ResearchCoverage,
    ResearchQuery,
    ResearchRun,
    ResearchRunStatus,
    SourceCoverage,
    allocate_result_limits,
)
from trendora.research.facebook import FacebookResearchRetriever
from trendora.research.retrieval import ResearchRetriever
from trendora.research.service import ResearchCapabilityResolver
from trendora.research.youtube import YouTubeResearchRetriever


def build_research_application_service(
    *,
    youtube_client: YouTubeClient | None,
    facebook_client: FacebookPublicClient | None = None,
    resolver: ResearchCapabilityResolver | None = None,
) -> ResearchApplicationService:
    """Build the application service with the runtime retrievers that exist.

    ``youtube_client`` / ``facebook_client`` are already-configured clients (or
    ``None`` when unavailable). Static capability truth is unchanged by runtime
    configuration: a statically-available source without a registered retriever
    raises ``ResearchSourceNotConfiguredError`` when requested.
    """
    retrievers: dict[str, ResearchRetriever] = {}
    if youtube_client is not None:
        retrievers["youtube"] = YouTubeResearchRetriever(youtube_client)
    if facebook_client is not None:
        retrievers["facebook"] = FacebookResearchRetriever(facebook_client)
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
        market: str,
        date_from: date,
        date_to: date,
        sources: Sequence[str],
        result_limit: int,
        facebook_page_id: str | None = None,
    ) -> ResearchRun:
        """Run research for a request and return the completed/blocked run.

        Domain validation happens inside ``ResearchQuery`` construction; the
        HTTP adapter never duplicates it.
        """
        query = ResearchQuery(
            topic=topic,
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
        """Build and execute the multi-source plan for a READY run.

        The plan contains every requested source whose capability resolved
        AVAILABLE, in normalized request order. Before any network call, every
        planned source must have a configured retriever — one missing
        retriever fails the whole request with the sanitized
        ``ResearchSourceNotConfiguredError`` and zero retrieval calls. The
        global ``result_limit`` is split deterministically across the plan
        (``divmod``; earlier requested sources take any remainder), and each
        retriever receives its own source-specific validated query.
        """
        coverage = run.coverage
        assert coverage is not None
        query = run.query
        plan: list[tuple[str, ResearchRetriever]] = []
        for source_code in query.source_codes:
            item = _source_coverage(coverage, source_code)
            if item is None or item.status is not CoverageStatus.AVAILABLE:
                continue
            retriever = self._retrievers.get(source_code)
            if retriever is None:
                # Available but unconfigured: fail closed before any call
                # instead of silently returning a partial combined result.
                raise ResearchSourceNotConfiguredError(
                    "no requested available source has a configured runtime retriever"
                )
            plan.append((source_code, retriever))
        if not plan:
            raise ResearchSourceNotConfiguredError(
                "no requested available source has a configured runtime retriever"
            )
        allocations = allocate_result_limits(
            query.result_limit, tuple(code for code, _ in plan)
        )
        entries = tuple(
            (source_code, _source_query(query, source_code, limit), retriever)
            for (source_code, retriever), (_, limit) in zip(plan, allocations, strict=True)
        )
        run.execute_sources(entries)


def _source_coverage(coverage: ResearchCoverage, source_code: str) -> SourceCoverage | None:
    for item in coverage.sources:
        if item.source_code == source_code:
            return item
    return None


def _source_query(query: ResearchQuery, source_code: str, limit: int) -> ResearchQuery:
    """A validated per-source query: own source code and allocated limit only.

    Facebook keeps ``facebook_page_id``; non-Facebook queries never carry one.
    Topic and market remain part of the shared contract. For Facebook they do
    not filter which Page posts are collected (documented limitation).
    """
    return ResearchQuery(
        topic=query.topic,
        market=query.market,
        date_from=query.date_from,
        date_to=query.date_to,
        source_codes=(source_code,),
        result_limit=limit,
        facebook_page_id=query.facebook_page_id if source_code == "facebook" else None,
    )
