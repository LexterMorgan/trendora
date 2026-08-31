"""Trendora research core (M13) and YouTube research retrieval (M14).

Deterministic, in-memory domain contracts for the evidence-backed research
direction (docs/14, docs/15, docs/16): ``ResearchQuery``, platform capability
declarations, coverage resolution, the ``ResearchRun`` lifecycle, and the
YouTube-first retrieval that produces normalized in-memory research
references. No persistence, no LLM.
"""

from trendora.research.capabilities import (
    KNOWN_SOURCE_CODES,
    default_declarations,
    required_capabilities,
)
from trendora.research.exceptions import (
    ResearchError,
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
    "ResearchQuery",
    "ResearchReference",
    "ResearchRun",
    "ResearchRunStatus",
    "ResearchStateError",
    "ResearchValidationError",
    "SourceCapabilities",
    "SourceCoverage",
    "YouTubeResearchRetriever",
    "default_declarations",
    "required_capabilities",
    "validate_research_query",
]
