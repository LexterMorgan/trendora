"""Grounded AI-interpretation contract (M19).

Defines exactly what deterministic evidence a future model may receive
(``EvidencePack``), what an interpretation may return (``AIInterpretation``),
how it cites evidence (typed citations), how citations are validated against
the pack, and how provider/model provenance is represented.

M19 calls no LLM and generates no interpretation. It only makes the future
boundary structurally sound: every accepted interpretation must cite evidence
that actually exists in the supplied pack. It does not and cannot prove that a
statement is semantically entailed by that evidence.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from trendora.research.evidence import (
    AnalysisBasis,
    ClaimType,
    ContentObservation,
    EvidenceFact,
    EvidenceField,
    ObservationType,
    ReferenceAnalysis,
    ReferenceId,
)
from trendora.research.exceptions import ResearchInterpretationError
from trendora.research.patterns import PatternAggregate

_FACT_FIELD_TO_BASIS: dict[EvidenceField, AnalysisBasis] = {
    EvidenceField.TITLE: AnalysisBasis.TITLE,
    EvidenceField.DESCRIPTION: AnalysisBasis.DESCRIPTION,
    EvidenceField.VIEW_COUNT: AnalysisBasis.RAW_METRICS,
    EvidenceField.LIKE_COUNT: AnalysisBasis.RAW_METRICS,
    EvidenceField.COMMENT_COUNT: AnalysisBasis.RAW_METRICS,
    EvidenceField.URL: AnalysisBasis.SOURCE_METADATA,
    EvidenceField.COLLECTED_AT: AnalysisBasis.SOURCE_METADATA,
    EvidenceField.PUBLISHED_AT: AnalysisBasis.SOURCE_METADATA,
    EvidenceField.CHANNEL_TITLE: AnalysisBasis.SOURCE_METADATA,
    EvidenceField.MARKET_CONTEXT: AnalysisBasis.SOURCE_METADATA,
    EvidenceField.MARKET_BASIS: AnalysisBasis.SOURCE_METADATA,
    EvidenceField.SOURCE_RANK: AnalysisBasis.SOURCE_METADATA,
}

_OBSERVATION_TYPE_TO_BASIS: dict[ObservationType, AnalysisBasis] = {
    ObservationType.TITLE_CHARACTER_COUNT: AnalysisBasis.TITLE,
    ObservationType.TITLE_HAS_NUMERAL: AnalysisBasis.TITLE,
    ObservationType.TITLE_HAS_QUESTION_MARK: AnalysisBasis.TITLE,
    ObservationType.DESCRIPTION_PRESENT: AnalysisBasis.DESCRIPTION,
    ObservationType.DESCRIPTION_CHARACTER_COUNT: AnalysisBasis.DESCRIPTION,
    ObservationType.DESCRIPTION_HAS_URL: AnalysisBasis.DESCRIPTION,
}

Citation = "FactCitation | ObservationCitation | PatternCitation"


@dataclass(frozen=True, slots=True)
class FactCitation:
    """Cite one direct source fact on one reference."""

    reference: ReferenceId
    field: EvidenceField


@dataclass(frozen=True, slots=True)
class ObservationCitation:
    """Cite one deterministic per-reference observation."""

    reference: ReferenceId
    observation_type: ObservationType


@dataclass(frozen=True, slots=True)
class PatternCitation:
    """Cite one cross-reference pattern aggregate."""

    observation_type: ObservationType


@dataclass(frozen=True, slots=True)
class EvidencePack:
    """Immutable deterministic material a future AI is allowed to reason over.

    Reuses M17 ``ReferenceAnalysis`` and M18 ``PatternAggregate`` directly —
    no source-truth duplication. Construction enforces integrity: non-empty,
    no duplicate reference ids, no duplicate pattern types, and every pattern
    provenance id must exist inside the pack. Ordering is preserved as given.
    """

    analyses: tuple[ReferenceAnalysis, ...]
    patterns: tuple[PatternAggregate, ...] = ()

    def __post_init__(self) -> None:
        if not self.analyses:
            raise ResearchInterpretationError("evidence pack must contain at least one analysis")
        reference_ids = [analysis.reference for analysis in self.analyses]
        if len(set(reference_ids)) != len(reference_ids):
            raise ResearchInterpretationError("evidence pack contains duplicate reference ids")
        pack_ids = set(reference_ids)
        seen_patterns: set[ObservationType] = set()
        for pattern in self.patterns:
            if pattern.observation_type in seen_patterns:
                raise ResearchInterpretationError(
                    f"evidence pack contains duplicate pattern {pattern.observation_type.value}"
                )
            seen_patterns.add(pattern.observation_type)
            provenance = (*pattern.matching_reference_ids, *pattern.non_matching_reference_ids)
            for provenance_id in provenance:
                if provenance_id not in pack_ids:
                    raise ResearchInterpretationError(
                        f"pattern {pattern.observation_type.value} references "
                        f"{provenance_id} outside the pack"
                    )


@dataclass(frozen=True, slots=True)
class AIInterpretation:
    """Semantic model output, explicitly grounded via typed citations.

    ``claim_type`` is always AI_INTERPRETATION (structural, not overridable).
    Construction enforces a non-blank statement, at least one citation, and no
    duplicate citations. Grounding against an EvidencePack happens later in
    ``validate_interpretations``.
    """

    statement: str
    citations: tuple[Citation, ...]
    claim_type: ClaimType = field(default=ClaimType.AI_INTERPRETATION, init=False)

    def __post_init__(self) -> None:
        if not self.statement or not self.statement.strip():
            raise ResearchInterpretationError("interpretation statement must not be blank")
        if not self.citations:
            raise ResearchInterpretationError("interpretation must cite at least one evidence item")
        if len(set(self.citations)) != len(self.citations):
            raise ResearchInterpretationError("interpretation contains duplicate citations")


@dataclass(frozen=True, slots=True)
class ModelProvenance:
    """Provider-neutral identity of the model that produced the interpretation.

    No hard-coded vendor list; provider/model are explicit non-blank strings.
    """

    provider: str
    model: str

    def __post_init__(self) -> None:
        if not self.provider or not self.provider.strip():
            raise ResearchInterpretationError("provider must not be blank")
        if not self.model or not self.model.strip():
            raise ResearchInterpretationError("model must not be blank")


@dataclass(frozen=True, slots=True)
class InterpretationResult:
    """Validated AI-interpretation output bundle."""

    model_provenance: ModelProvenance
    interpretations: tuple[AIInterpretation, ...]


def validate_citations(pack: EvidencePack, citations: tuple[Citation, ...]) -> None:
    """Resolve every citation against the pack; raise on any invalid citation."""
    analysis_by_id = {analysis.reference: analysis for analysis in pack.analyses}
    patterns_by_type = {pattern.observation_type: pattern for pattern in pack.patterns}
    for citation in citations:
        _resolve_citation(citation, analysis_by_id, patterns_by_type)


def validate_interpretations(
    pack: EvidencePack,
    result: InterpretationResult,
) -> InterpretationResult:
    """Structurally validate every interpretation's citations against the pack.

    Returns the result unchanged on success; raises
    ``ResearchInterpretationError`` on any unknown reference, unresolved
    fact/observation/pattern citation, or empty citation set.
    """
    for interpretation in result.interpretations:
        if interpretation.claim_type is not ClaimType.AI_INTERPRETATION:
            raise ResearchInterpretationError("interpretation claim_type must be AI_INTERPRETATION")
        validate_citations(pack, interpretation.citations)
    return result


def _resolve_citation(
    citation: Citation,
    analysis_by_id: dict[ReferenceId, ReferenceAnalysis],
    patterns_by_type: dict[ObservationType, PatternAggregate],
) -> None:
    if isinstance(citation, PatternCitation):
        if citation.observation_type not in patterns_by_type:
            raise ResearchInterpretationError(
                f"pattern citation {citation.observation_type.value} is absent from the pack"
            )
        return
    analysis = analysis_by_id.get(citation.reference)
    if analysis is None:
        raise ResearchInterpretationError(
            f"citation references unknown reference {citation.reference}"
        )
    if isinstance(citation, FactCitation):
        if not any(fact.field is citation.field for fact in analysis.facts):
            raise ResearchInterpretationError(
                f"reference {citation.reference} has no fact {citation.field.value}"
            )
        return
    if not any(
        observation.observation_type is citation.observation_type
        for observation in analysis.observations
    ):
        raise ResearchInterpretationError(
            f"reference {citation.reference} has no observation "
            f"{citation.observation_type.value}"
        )


def interpretation_analysis_basis(pack: EvidencePack, citation: Citation) -> AnalysisBasis:
    """Derive the analysis basis of a validated citation.

    Fact citations map via ``EvidenceField``; observation citations read the
    actual observation's ``analysis_basis`` from the pack; pattern citations
    derive from the underlying M17 observation semantics. Raises on invalid
    citations. No caller-declared basis is accepted.
    """
    if isinstance(citation, PatternCitation):
        if citation.observation_type not in _OBSERVATION_TYPE_TO_BASIS:
            raise ResearchInterpretationError(
                f"no basis mapping for pattern {citation.observation_type.value}"
            )
        return _OBSERVATION_TYPE_TO_BASIS[citation.observation_type]
    analysis = next(
        (item for item in pack.analyses if item.reference == citation.reference), None
    )
    if analysis is None:
        raise ResearchInterpretationError(
            f"citation references unknown reference {citation.reference}"
        )
    if isinstance(citation, FactCitation):
        basis = _FACT_FIELD_TO_BASIS.get(citation.field)
        if basis is None:
            raise ResearchInterpretationError(
                f"no basis mapping for fact field {citation.field.value}"
            )
        if not any(fact.field is citation.field for fact in analysis.facts):
            raise ResearchInterpretationError(
                f"reference {citation.reference} has no fact {citation.field.value}"
            )
        return basis
    observation = next(
        (
            obs
            for obs in analysis.observations
            if obs.observation_type is citation.observation_type
        ),
        None,
    )
    if observation is None:
        raise ResearchInterpretationError(
            f"reference {citation.reference} has no observation "
            f"{citation.observation_type.value}"
        )
    return observation.analysis_basis
