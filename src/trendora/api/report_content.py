"""On-demand content generation from an immutable research report snapshot.

The source row is never mutated. A successful operation appends a new completed
report snapshot with the same research/evidence/interpretation plus generated
strategy and ideation. That keeps existing fingerprints, recovery receipts, and
historical reports intact without a migration.
"""

from __future__ import annotations

from typing import Any

from trendora.api.errors import ApiError
from trendora.research.evidence import (
    AnalysisBasis,
    ContentObservation,
    EvidenceFact,
    EvidenceField,
    ObservationType,
    ReferenceAnalysis,
    ReferenceId,
)
from trendora.research.exceptions import ResearchInterpretationError
from trendora.research.ideation import IdeationContext
from trendora.research.interpretation import (
    AIInterpretation,
    EvidencePack,
    FactCitation,
    InterpretationResult,
    ModelProvenance,
    ObservationCitation,
    PatternCitation,
)
from trendora.research.patterns import PatternAggregate
from trendora.research.strategy import StrategicContext


class ReportContentNotAvailableError(ApiError):
    status_code = 422
    code = "content_not_available"


class ReportContentConflictError(ApiError):
    status_code = 409
    code = "content_already_partial"


class ReportContentProviderUnavailableError(ApiError):
    status_code = 503
    code = "content_provider_unavailable"


class ReportContentGenerationError(ApiError):
    status_code = 502
    code = "content_generation_unavailable"


def _reference_id(value: dict[str, Any]) -> ReferenceId:
    return ReferenceId(
        source_code=str(value["source_code"]),
        content_external_id=str(value["content_external_id"]),
    )


def _citation(value: dict[str, Any]):
    kind = value.get("kind")
    if kind == "fact":
        return FactCitation(
            reference=_reference_id(value["reference"]),
            field=EvidenceField(value["field"]),
        )
    if kind == "observation":
        return ObservationCitation(
            reference=_reference_id(value["reference"]),
            observation_type=ObservationType(value["observation_type"]),
        )
    if kind == "pattern":
        return PatternCitation(observation_type=ObservationType(value["observation_type"]))
    raise ResearchInterpretationError("stored citation has an unknown kind")


def _analysis_bases(fields: tuple[str, ...]) -> tuple[AnalysisBasis, ...]:
    bases: list[AnalysisBasis] = []
    for field in fields:
        if field == EvidenceField.TITLE:
            basis = AnalysisBasis.TITLE
        elif field == EvidenceField.DESCRIPTION:
            basis = AnalysisBasis.DESCRIPTION
        elif field in {
            EvidenceField.VIEW_COUNT, EvidenceField.LIKE_COUNT,
            EvidenceField.COMMENT_COUNT, EvidenceField.REACTION_COUNT,
            EvidenceField.SHARE_COUNT,
        }:
            basis = AnalysisBasis.RAW_METRICS
        else:
            basis = AnalysisBasis.SOURCE_METADATA
        if basis not in bases:
            bases.append(basis)
    return tuple(bases)


def build_content_context(snapshot: dict[str, Any]) -> tuple[EvidencePack, InterpretationResult]:
    """Reconstruct the exact stored evidence and interpretation for content work.

    No new evidence is collected and no source facts are changed. The stored
    pack is authoritative, including the full 40-reference sample when present.
    """
    evidence = snapshot.get("evidence")
    interpretation = snapshot.get("interpretation")
    if not isinstance(evidence, dict) or not isinstance(interpretation, dict):
        raise ResearchInterpretationError("report has no evidence or interpretation")

    analyses: list[ReferenceAnalysis] = []
    for raw in evidence.get("analyses") or []:
        ref = _reference_id(raw["reference_id"])
        facts = tuple(
            EvidenceFact(ref, EvidenceField(fact["field"]), fact.get("value"))
            for fact in raw.get("facts") or []
        )
        observations = tuple(
            ContentObservation(
                ref,
                ObservationType(obs["observation_type"]),
                obs.get("value"),
                tuple(EvidenceField(field) for field in obs.get("evidence_fields") or []),
                AnalysisBasis(obs["analysis_basis"]),
            )
            for obs in raw.get("observations") or []
        )
        analyses.append(
            ReferenceAnalysis(
                reference=ref,
                analysis_basis=_analysis_bases(tuple(fact.field.value for fact in facts)),
                facts=facts,
                observations=observations,
            )
        )
    patterns = tuple(
        PatternAggregate(
            observation_type=ObservationType(raw["observation_type"]),
            analyzed_count=int(raw["analyzed_count"]),
            matching_count=int(raw["matching_count"]),
            non_matching_count=int(raw["non_matching_count"]),
            ratio=float(raw["ratio"]),
            matching_reference_ids=tuple(_reference_id(item) for item in raw.get("matching_reference_ids") or []),
            non_matching_reference_ids=tuple(_reference_id(item) for item in raw.get("non_matching_reference_ids") or []),
        )
        for raw in evidence.get("patterns") or []
    )
    pack = EvidencePack(tuple(analyses), patterns)
    result = InterpretationResult(
        model_provenance=ModelProvenance(
            provider=str(interpretation["model_provenance"]["provider"]),
            model=str(interpretation["model_provenance"]["model"]),
        ),
        interpretations=tuple(
            AIInterpretation(
                statement=str(item["statement"]),
                citations=tuple(_citation(citation) for citation in item.get("citations") or []),
            )
            for item in interpretation.get("interpretations") or []
        ),
    )
    return pack, result


def build_content_contexts(pack: EvidencePack, interpretation: InterpretationResult, strategy):
    """Build validated strategy/ideation contexts in the existing order."""
    strategic = StrategicContext(pack, interpretation)
    ideation = IdeationContext(strategic, strategy)
    return strategic, ideation
