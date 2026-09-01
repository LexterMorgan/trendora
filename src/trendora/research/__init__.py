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
from trendora.research.evidence import (
    AnalysisBasis,
    ClaimType,
    ContentObservation,
    EvidenceFact,
    EvidenceField,
    ObservationType,
    ReferenceAnalysis,
    ReferenceId,
    analyze_reference,
    analyze_references,
    extract_evidence,
    reference_id,
)
from trendora.research.exceptions import (
    ResearchAggregationError,
    ResearchError,
    ResearchInterpretationError,
    ResearchNoCoverageError,
    ResearchSourceNotConfiguredError,
    ResearchStateError,
    ResearchValidationError,
)
from trendora.research.interpretation import (
    AIInterpretation,
    EvidencePack,
    FactCitation,
    InterpretationResult,
    ModelProvenance,
    ObservationCitation,
    PatternCitation,
    interpretation_analysis_basis,
    validate_interpretations,
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
from trendora.research.patterns import (
    BOOLEAN_OBSERVATION_TYPES,
    PatternAggregate,
    aggregate_patterns,
)
from trendora.research.service import ResearchCapabilityResolver
from trendora.research.youtube import YouTubeResearchRetriever

__all__ = [
    "AIInterpretation",
    "AnalysisBasis",
    "BOOLEAN_OBSERVATION_TYPES",
    "ClaimType",
    "ContentObservation",
    "DEFAULT_RESULT_LIMIT",
    "DEFAULT_SOURCE_CODES",
    "EvidenceFact",
    "EvidenceField",
    "EvidencePack",
    "FactCitation",
    "InterpretationResult",
    "KNOWN_SOURCE_CODES",
    "MAX_RESULT_LIMIT",
    "MARKET_CODES",
    "ModelProvenance",
    "ObservationCitation",
    "ObservationType",
    "PatternAggregate",
    "PatternCitation",
    "ReferenceAnalysis",
    "ReferenceId",
    "ResearchAggregationError",
    "ResearchInterpretationError",
    "aggregate_patterns",
    "analyze_reference",
    "analyze_references",
    "extract_evidence",
    "interpretation_analysis_basis",
    "reference_id",
    "validate_interpretations",
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
