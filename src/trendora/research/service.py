"""Deterministic capability/coverage resolution (M13).

Maps a validated ``ResearchQuery`` against static source capability
declarations and produces an explicit ``ResearchCoverage`` result. No network,
no persistence, no retrieval. The core invariant:

    TRENDORA MUST NEVER REPORT A SOURCE AS AVAILABLE/SEARCHED FOR A
    CAPABILITY THE SOURCE DECLARATION DOES NOT SUPPORT.
"""

from __future__ import annotations

from collections.abc import Mapping

from trendora.research.capabilities import (
    KNOWN_SOURCE_CODES,
    default_declarations,
    required_capabilities,
)
from trendora.research.models import (
    CoverageCompleteness,
    CoverageReason,
    CoverageStatus,
    PlatformCapability,
    ResearchCoverage,
    ResearchQuery,
    SourceCapabilities,
    SourceCoverage,
)


class ResearchCapabilityResolver:
    """Resolves a ResearchQuery against capability declarations."""

    def __init__(
        self,
        declarations: Mapping[str, SourceCapabilities] | None = None,
    ) -> None:
        self._declarations = dict(declarations) if declarations is not None else default_declarations()

    @property
    def declarations(self) -> dict[str, SourceCapabilities]:
        """Copy of the active declarations (read-only access for callers/tests)."""
        return dict(self._declarations)

    def resolve(self, query: ResearchQuery) -> ResearchCoverage:
        coverages: list[SourceCoverage] = []
        for capability in required_capabilities(query):
            for source_code in query.source_codes:
                coverages.append(self._resolve_source(source_code, capability))
        return ResearchCoverage(
            sources=tuple(coverages),
            completeness=_completeness(coverages),
        )

    def _resolve_source(
        self,
        source_code: str,
        capability: PlatformCapability,
    ) -> SourceCoverage:
        if source_code not in KNOWN_SOURCE_CODES:
            return SourceCoverage(
                source_code=source_code,
                capability=capability,
                status=CoverageStatus.UNAVAILABLE,
                reason=CoverageReason.SOURCE_UNKNOWN,
            )
        declaration = self._declarations.get(source_code)
        if declaration is None:
            return SourceCoverage(
                source_code=source_code,
                capability=capability,
                status=CoverageStatus.UNAVAILABLE,
                reason=CoverageReason.CAPABILITY_NOT_SUPPORTED,
            )
        if capability in declaration.supported:
            return SourceCoverage(
                source_code=source_code,
                capability=capability,
                status=CoverageStatus.AVAILABLE,
            )
        if capability in declaration.conditional:
            return SourceCoverage(
                source_code=source_code,
                capability=capability,
                status=CoverageStatus.CONDITIONAL,
                reason=CoverageReason.AUTHORIZATION_REQUIRED,
            )
        return SourceCoverage(
            source_code=source_code,
            capability=capability,
            status=CoverageStatus.UNAVAILABLE,
            reason=CoverageReason.CAPABILITY_NOT_SUPPORTED,
        )


def _completeness(coverages: list[SourceCoverage]) -> CoverageCompleteness:
    available = sum(1 for item in coverages if item.status is CoverageStatus.AVAILABLE)
    if available == len(coverages):
        return CoverageCompleteness.COMPLETE
    if available == 0:
        return CoverageCompleteness.NONE
    return CoverageCompleteness.PARTIAL
