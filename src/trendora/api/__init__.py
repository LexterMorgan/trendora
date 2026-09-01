"""Trendora HTTP API layer (M11B forecast, M15 research).

Thin FastAPI adapters. The forecast endpoint exposes the M10 GitHub forecast
product; the research endpoint exposes the M15 research application service.
No SQL, no connectors, no persistence, no auth, no rate limiting in the
adapter layer.
"""

from trendora.api.app import (
    create_app,
    get_github_forecast_product,
    get_research_application_service,
    get_research_report_service,
)
from trendora.api.models import ForecastPointResponse, ForecastResponse
from trendora.api.research_models import (
    ResearchCoverageResponse,
    ResearchMetricsResponse,
    ResearchQueryResponse,
    ResearchReferenceResponse,
    ResearchRequest,
    ResearchResponse,
    SourceCoverageResponse,
)
from trendora.api.research_report_models import (
    ContentBriefResponse,
    ContentGapResponse,
    ContentIdeaResponse,
    EvidenceAnalysisResponse,
    EvidenceFactResponse,
    EvidencePackResponse,
    IdeationResultResponse,
    InterpretationItemResponse,
    InterpretationResultResponse,
    ModelProvenanceResponse,
    OpportunityResponse,
    PatternAggregateResponse,
    ReferenceIdResponse,
    ResearchReportRequest,
    ResearchReportResponse,
    StrategicResultResponse,
    to_report_response,
)

__all__ = [
    "ContentBriefResponse",
    "ContentGapResponse",
    "ContentIdeaResponse",
    "EvidenceAnalysisResponse",
    "EvidenceFactResponse",
    "EvidencePackResponse",
    "ForecastPointResponse",
    "ForecastResponse",
    "IdeationResultResponse",
    "InterpretationItemResponse",
    "InterpretationResultResponse",
    "ModelProvenanceResponse",
    "OpportunityResponse",
    "PatternAggregateResponse",
    "ReferenceIdResponse",
    "ResearchCoverageResponse",
    "ResearchMetricsResponse",
    "ResearchQueryResponse",
    "ResearchReferenceResponse",
    "ResearchReportRequest",
    "ResearchReportResponse",
    "ResearchRequest",
    "ResearchResponse",
    "SourceCoverageResponse",
    "StrategicResultResponse",
    "create_app",
    "get_github_forecast_product",
    "get_research_application_service",
    "get_research_report_service",
    "to_report_response",
]
