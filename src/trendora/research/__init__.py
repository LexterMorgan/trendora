"""Trendora research core (M13), retrieval (M14), and application service (M15).

Deterministic, in-memory domain contracts for the evidence-backed research
direction (docs/14, docs/15, docs/16, docs/17): ``ResearchQuery``, platform
capability declarations, coverage resolution, the ``ResearchRun`` lifecycle,
YouTube-first retrieval producing normalized in-memory references, and the
synchronous application service the HTTP adapter calls. No persistence, no LLM.
"""

from trendora.research.application import ResearchApplicationService
from trendora.research.capabilities import (
    KNOWN_SOURCE_CODES,
    default_declarations,
    required_capabilities,
)
from trendora.research.exceptions import (
    ResearchError,
    ResearchNoCoverageError,
    ResearchSourceNotConfiguredError,
    ResearchStateError,
    ResearchValidationError,
)
from trendora.research.models import (
    DEFAULT_RESULT_LIMIT,
    DEFAULT_SOURCE_CODES,
    MAX_RESULT_LIMIT,
    MARKET_CODES,
    CoverageCompleteness,
    CoverageReason,
    CoverageStatus,
    MarketBasis,
    PlatformCapability,
    ResearchCoverage,
    ResearchMetrics,
    ResearchQuery,
    ResearchReference,
    ResearchRun,
    ResearchRunStatus,
    SourceCapabilities,
    SourceCoverage,
    validate_research_query,
)
from trendora.research.service import ResearchCapabilityResolver
from trendora.research.youtube import YouTubeResearchRetriever

__all__ = [
    "DEFAULT_RESULT_LIMIT",
    "DEFAULT_SOURCE_CODES",
    "KNOWN_SOURCE_CODES",
    "MAX_RESULT_LIMIT",
    "MARKET_CODES",
    "CoverageCompleteness",
    "CoverageReason",
    "CoverageStatus",
    "MarketBasis",
    "PlatformCapability",
    "ResearchCapabilityResolver",
    "ResearchCoverage",
    "ResearchError",
    "ResearchMetrics",
    "ResearchNoCoverageError",
    "ResearchQuery",
    "ResearchReference",
    "ResearchRun",
    "ResearchRunStatus",
    "ResearchSourceNotConfiguredError",
    "ResearchStateError",
    "ResearchValidationError",
    "ResearchApplicationService",
    "SourceCapabilities",
    "SourceCoverage",
    "YouTubeResearchRetriever",
    "default_declarations",
    "required_capabilities",
    "validate_research_query",
]
