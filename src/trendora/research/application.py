"""Research application service (M15).

Thin synchronous orchestration over the M13/M14 research domain. It is the
single application entry point the HTTP adapter calls.

Flow:
    validated inputs
      → construct/validate ResearchQuery
      → resolve capability coverage
      → create ResearchRun (READY | BLOCKED)
      → execute the registered runtime retriever for the first available
        requested source
      → return the ResearchRun

Explicit and small: no command bus, workflow engine, event bus, plugin
framework, or DI container. Static capability truth and runtime retriever
availability are separate: an available source without a registered retriever
raises ``ResearchSourceNotConfiguredError``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from trendora.connectors.youtube.client import YouTubeClient
from trendora.research.exceptions import ResearchSourceNotConfiguredError
from trendora.research.models import (
    CoverageStatus,
    ResearchCoverage,
    ResearchQuery,
    ResearchRun,
    ResearchRunStatus,
    SourceCoverage,
)
from trendora.research.service import ResearchCapabilityResolver
from trendora.research.youtube import YouTubeResearchRetriever


def build_research_application_service(
    *,
    youtube_client: YouTubeClient | None,
    resolver: ResearchCapabilityResolver | None = None,
) -> ResearchApplicationService:
    """Build the application service with the runtime retrievers that exist.

    ``youtube_client`` is the already-configured YouTube client (or ``None``
    when no API key is available). Static capability truth is unchanged by
    runtime configuration: with no client, YouTube stays ``available`` but a
    request that needs it raises ``ResearchSourceNotConfiguredError``.
    """
    retrievers: dict[str, YouTubeResearchRetriever] = {}
    if youtube_client is not None:
        retrievers["youtube"] = YouTubeResearchRetriever(youtube_client)
    return ResearchApplicationService(
        resolver=resolver or ResearchCapabilityResolver(),
        retrievers=retrievers,
    )


class ResearchApplicationService:
    """Executes one synchronous research request and returns the run."""

    def __init__(
        self,
        resolver: ResearchCapabilityResolver,
        retrievers: Mapping[str, YouTubeResearchRetriever],
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
        )
        run = ResearchRun(query)
        run.resolve_capabilities(self._resolver)
        if run.status is not ResearchRunStatus.READY:
            return run
        self._execute_available(run)
        return run

    def _execute_available(self, run: ResearchRun) -> None:
        coverage = run.coverage
        assert coverage is not None
        for source_code in run.query.source_codes:
            item = _source_coverage(coverage, source_code)
            if item is None or item.status is not CoverageStatus.AVAILABLE:
                continue
            retriever = self._retrievers.get(source_code)
            if retriever is None:
                # Statically available but no runtime retriever: not executable.
                # Keep scanning so a later genuinely executable source wins.
                continue
            run.execute(source_code, retriever)
            return
        raise ResearchSourceNotConfiguredError(
            "no requested available source has a configured runtime retriever"
        )


def _source_coverage(coverage: ResearchCoverage, source_code: str) -> SourceCoverage | None:
    for item in coverage.sources:
        if item.source_code == source_code:
            return item
    return None
