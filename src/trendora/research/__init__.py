"""Trendora research core (M13).

Deterministic, in-memory domain contracts for the evidence-backed research
direction (docs/14, docs/15): ``ResearchQuery``, platform capability
declarations, coverage resolution, and the synchronous ``ResearchRun``
lifecycle. No network, no persistence, no connectors, no LLM.
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
    PlatformCapability,
    ResearchCoverage,
    ResearchQuery,
    ResearchRun,
    ResearchRunStatus,
    SourceCapabilities,
    SourceCoverage,
    validate_research_query,
)
from trendora.research.service import ResearchCapabilityResolver

__all__ = [
    "DEFAULT_RESULT_LIMIT",
    "DEFAULT_SOURCE_CODES",
    "KNOWN_SOURCE_CODES",
    "MAX_RESULT_LIMIT",
    "MARKET_CODES",
    "CoverageCompleteness",
    "CoverageReason",
    "CoverageStatus",
    "PlatformCapability",
    "ResearchCapabilityResolver",
    "ResearchCoverage",
    "ResearchError",
    "ResearchQuery",
    "ResearchRun",
    "ResearchRunStatus",
    "ResearchStateError",
    "ResearchValidationError",
    "SourceCapabilities",
    "SourceCoverage",
    "default_declarations",
    "required_capabilities",
    "validate_research_query",
]
