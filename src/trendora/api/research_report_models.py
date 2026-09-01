"""HTTP response models for the M23A research report endpoint.

Explicit serialization of the report domain. Citations reuse the exact M20
citation JSON shapes via ``citation_to_json``. Datetimes are timezone-aware
ISO 8601; enums are stable strings; missing metrics stay null; zero stays 0.
No resolved claims, flattened provenance, scores, or rankings.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict

from trendora.api.research_models import ResearchRequest, ResearchResponse, to_research_response
from trendora.research.ai_provider import evidence_pack_to_payload
from trendora.research.ideation import IdeationResult
from trendora.research.interpretation import InterpretationResult
from trendora.research.reporting import ResearchReport
from trendora.research.strategy import StrategicResult, citation_to_json


class ResearchReportRequest(ResearchRequest):
    """Same body as M15 research, but unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class ModelProvenanceResponse(BaseModel):
    provider: str
    model: str


class ReferenceIdResponse(BaseModel):
    source_code: str
    content_external_id: str


class EvidenceFactResponse(BaseModel):
    field: str
    value: Any


class ContentObservationResponse(BaseModel):
    observation_type: str
    value: Any
    evidence_fields: list[str]
    analysis_basis: str


class EvidenceAnalysisResponse(BaseModel):
    reference_id: ReferenceIdResponse
    facts: list[EvidenceFactResponse]
    observations: list[ContentObservationResponse]


class PatternAggregateResponse(BaseModel):
    observation_type: str
    analyzed_count: int
    matching_count: int
    non_matching_count: int
    ratio: float
    matching_reference_ids: list[ReferenceIdResponse]
    non_matching_reference_ids: list[ReferenceIdResponse]


class EvidencePackResponse(BaseModel):
    analyses: list[EvidenceAnalysisResponse]
    patterns: list[PatternAggregateResponse]


class InterpretationItemResponse(BaseModel):
    statement: str
    citations: list[dict[str, Any]]


class InterpretationResultResponse(BaseModel):
    model_provenance: ModelProvenanceResponse
    interpretations: list[InterpretationItemResponse]


class ContentGapResponse(BaseModel):
    statement: str
    supporting_interpretation_indexes: list[int]
    citations: list[dict[str, Any]]


class OpportunityResponse(BaseModel):
    statement: str
    gap_indexes: list[int]
    citations: list[dict[str, Any]]


class StrategicResultResponse(BaseModel):
    model_provenance: ModelProvenanceResponse
    content_gaps: list[ContentGapResponse]
    opportunities: list[OpportunityResponse]


class ContentIdeaResponse(BaseModel):
    title: str
    angle: str
    opportunity_indexes: list[int]
    citations: list[dict[str, Any]]


class ContentBriefResponse(BaseModel):
    idea_index: int
    objective: str
    format: str
    hook: str
    outline: list[str]
    citations: list[dict[str, Any]]


class IdeationResultResponse(BaseModel):
    model_provenance: ModelProvenanceResponse
    content_ideas: list[ContentIdeaResponse]
    content_briefs: list[ContentBriefResponse]


class ResearchReportResponse(BaseModel):
    status: str
    research: ResearchResponse
    evidence: EvidencePackResponse | None
    interpretation: InterpretationResultResponse | None
    strategy: StrategicResultResponse | None
    ideation: IdeationResultResponse | None


def to_report_response(report: ResearchReport) -> ResearchReportResponse:
    """Serialize a validated ``ResearchReport``. Pure serialization only."""
    research = to_research_response(report.research_run)
    return ResearchReportResponse(
        status=report.status.value,
        research=research,
        evidence=_to_evidence(report.evidence_pack),
        interpretation=_to_interpretation(report.interpretation_result),
        strategy=_to_strategy(report.strategic_result),
        ideation=_to_ideation(report.ideation_result),
    )


def _to_evidence(pack) -> EvidencePackResponse | None:
    if pack is None:
        return None
    payload = evidence_pack_to_payload(pack)
    return EvidencePackResponse(
        analyses=[
            EvidenceAnalysisResponse(
                reference_id=ReferenceIdResponse(**item["reference_id"]),
                facts=[EvidenceFactResponse(**fact) for fact in item["facts"]],
                observations=[ContentObservationResponse(**obs) for obs in item["observations"]],
            )
            for item in payload["references"]
        ],
        patterns=[
            PatternAggregateResponse(
                observation_type=pattern["observation_type"],
                analyzed_count=pattern["analyzed_count"],
                matching_count=pattern["matching_count"],
                non_matching_count=pattern["non_matching_count"],
                ratio=pattern["ratio"],
                matching_reference_ids=[
                    ReferenceIdResponse(**rid) for rid in pattern["matching_reference_ids"]
                ],
                non_matching_reference_ids=[
                    ReferenceIdResponse(**rid) for rid in pattern["non_matching_reference_ids"]
                ],
            )
            for pattern in payload["patterns"]
        ],
    )


def _to_interpretation(result: InterpretationResult | None) -> InterpretationResultResponse | None:
    if result is None:
        return None
    return InterpretationResultResponse(
        model_provenance=_to_provenance(result.model_provenance),
        interpretations=[
            InterpretationItemResponse(
                statement=item.statement,
                citations=[citation_to_json(citation) for citation in item.citations],
            )
            for item in result.interpretations
        ],
    )


def _to_strategy(result: StrategicResult | None) -> StrategicResultResponse | None:
    if result is None:
        return None
    return StrategicResultResponse(
        model_provenance=_to_provenance(result.model_provenance),
        content_gaps=[
            ContentGapResponse(
                statement=gap.statement,
                supporting_interpretation_indexes=list(gap.supporting_interpretation_indexes),
                citations=[citation_to_json(citation) for citation in gap.citations],
            )
            for gap in result.content_gaps
        ],
        opportunities=[
            OpportunityResponse(
                statement=opportunity.statement,
                gap_indexes=list(opportunity.gap_indexes),
                citations=[citation_to_json(citation) for citation in opportunity.citations],
            )
            for opportunity in result.opportunities
        ],
    )


def _to_ideation(result: IdeationResult | None) -> IdeationResultResponse | None:
    if result is None:
        return None
    return IdeationResultResponse(
        model_provenance=_to_provenance(result.model_provenance),
        content_ideas=[
            ContentIdeaResponse(
                title=idea.title,
                angle=idea.angle,
                opportunity_indexes=list(idea.opportunity_indexes),
                citations=[citation_to_json(citation) for citation in idea.citations],
            )
            for idea in result.content_ideas
        ],
        content_briefs=[
            ContentBriefResponse(
                idea_index=brief.idea_index,
                objective=brief.objective,
                format=brief.format,
                hook=brief.hook,
                outline=list(brief.outline),
                citations=[citation_to_json(citation) for citation in brief.citations],
            )
            for brief in result.content_briefs
        ],
    )


def _to_provenance(provenance) -> ModelProvenanceResponse:
    return ModelProvenanceResponse(provider=provenance.provider, model=provenance.model)
