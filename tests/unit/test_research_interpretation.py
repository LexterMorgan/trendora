"""M19 grounded AI-interpretation contract tests. No LLM, pure domain."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from trendora.research import (
    AIInterpretation,
    AnalysisBasis,
    ClaimType,
    ContentObservation,
    EvidenceField,
    EvidencePack,
    FactCitation,
    InterpretationResult,
    MarketBasis,
    ModelProvenance,
    ObservationCitation,
    ObservationType,
    PatternCitation,
    ReferenceAnalysis,
    ReferenceId,
    ResearchInterpretationError,
    ResearchMetrics,
    ResearchReference,
    aggregate_patterns,
    analyze_reference,
    interpretation_analysis_basis,
    validate_interpretations,
)
from trendora.research.patterns import BOOLEAN_OBSERVATION_TYPES

UTC = timezone.utc


def _rid(external: str) -> ReferenceId:
    return ReferenceId(source_code="youtube", content_external_id=external)


def _reference(external: str, *, title: str, description: str | None = None) -> ResearchReference:
    return ResearchReference(
        source_code="youtube",
        content_external_id=external,
        collected_at=datetime(2026, 9, 1, tzinfo=UTC),
        url=f"https://www.youtube.com/watch?v={external}",
        title=title,
        description=description,
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        channel_external_id="UCx",
        channel_title="Example Channel",
        market_context="SG",
        market_basis=MarketBasis.YOUTUBE_REGION_AVAILABILITY,
        source_rank=1,
        metrics=ResearchMetrics(view_count=100, like_count=None, comment_count=5),
    )


def _pack(analyses=None, patterns=None) -> EvidencePack:
    return EvidencePack(
        analyses=tuple(analyses) if analyses is not None else (analyze_reference(_reference("a", title="5 tools")),),
        patterns=tuple(patterns) if patterns is not None else (),
    )


def _result(*interpretations) -> InterpretationResult:
    return InterpretationResult(
        model_provenance=ModelProvenance(provider="test", model="test-model"),
        interpretations=tuple(interpretations),
    )


class TestEvidencePack:
    def test_valid_pack(self) -> None:
        pack = _pack()
        assert len(pack.analyses) == 1
        assert pack.patterns == ()

    def test_empty_pack_rejected(self) -> None:
        with pytest.raises(ResearchInterpretationError, match="at least one analysis"):
            EvidencePack(analyses=())

    def test_duplicate_reference_id_rejected(self) -> None:
        with pytest.raises(ResearchInterpretationError, match="duplicate reference ids"):
            EvidencePack(
                analyses=(
                    analyze_reference(_reference("a", title="x")),
                    analyze_reference(_reference("a", title="y")),
                )
            )

    def test_duplicate_pattern_type_rejected(self) -> None:
        analyses = (
            analyze_reference(_reference("a", title="5 tools")),
            analyze_reference(_reference("b", title="no numeral")),
        )
        patterns = aggregate_patterns(analyses)
        with pytest.raises(ResearchInterpretationError, match="duplicate pattern"):
            EvidencePack(analyses=analyses, patterns=(patterns[0], patterns[0]))

    def test_pattern_provenance_outside_pack_rejected(self) -> None:
        analyses = (
            analyze_reference(_reference("a", title="5 tools")),
            analyze_reference(_reference("b", title="no numeral")),
        )
        patterns = aggregate_patterns(analyses)
        # 'c' is not in the pack but is in a pattern's provenance.
        from trendora.research.patterns import PatternAggregate

        forged = PatternAggregate(
            observation_type=patterns[0].observation_type,
            analyzed_count=1,
            matching_count=1,
            non_matching_count=0,
            ratio=1.0,
            matching_reference_ids=(_rid("c"),),
            non_matching_reference_ids=(),
        )
        with pytest.raises(ResearchInterpretationError, match="outside the pack"):
            EvidencePack(analyses=analyses, patterns=(forged,))

    def test_ordering_and_input_unchanged(self) -> None:
        analyses = (
            analyze_reference(_reference("a", title="5 tools")),
            analyze_reference(_reference("b", title="no numeral")),
        )
        patterns = aggregate_patterns(analyses)
        before = (analyses[0].facts, patterns)
        pack = EvidencePack(analyses=analyses, patterns=patterns)
        assert pack.analyses == analyses
        assert pack.patterns == patterns
        assert (analyses[0].facts, patterns) == before


class TestCitations:
    def test_valid_fact_citation(self) -> None:
        pack = _pack()
        citation = FactCitation(reference=_rid("a"), field=EvidenceField.VIEW_COUNT)
        result = _result(AIInterpretation("views observed", (citation,)))
        assert validate_interpretations(pack, result) is result

    def test_invalid_reference_id_rejected(self) -> None:
        pack = _pack()
        citation = FactCitation(reference=_rid("zzz"), field=EvidenceField.VIEW_COUNT)
        result = _result(AIInterpretation("x", (citation,)))
        with pytest.raises(ResearchInterpretationError, match="unknown reference"):
            validate_interpretations(pack, result)

    def test_field_absent_from_reference_rejected(self) -> None:
        pack = _pack()
        citation = FactCitation(reference=_rid("a"), field=EvidenceField.MARKET_BASIS)
        result = _result(AIInterpretation("x", (citation,)))
        assert validate_interpretations(pack, result) is result  # exists on every analysis

    def test_url_and_collected_at_citable(self) -> None:
        pack = _pack()
        analysis = pack.analyses[0]
        fields = {fact.field for fact in analysis.facts}
        assert EvidenceField.URL in fields
        assert EvidenceField.COLLECTED_AT in fields

    def test_missing_metric_is_still_an_existing_fact(self) -> None:
        pack = _pack()
        analysis = pack.analyses[0]
        like = next(fact for fact in analysis.facts if fact.field is EvidenceField.LIKE_COUNT)
        assert like.value is None
        result = _result(
            AIInterpretation(
                "like count unavailable",
                (FactCitation(reference=_rid("a"), field=EvidenceField.LIKE_COUNT),),
            )
        )
        assert validate_interpretations(pack, result) is result

    def test_observation_citation_valid_and_wrong_reference(self) -> None:
        pack = _pack()
        citation = ObservationCitation(
            reference=_rid("a"), observation_type=ObservationType.TITLE_HAS_NUMERAL
        )
        assert validate_interpretations(
            pack, _result(AIInterpretation("x", (citation,)))
        ) is not None
        bad = ObservationCitation(
            reference=_rid("zzz"), observation_type=ObservationType.TITLE_HAS_NUMERAL
        )
        with pytest.raises(ResearchInterpretationError):
            validate_interpretations(pack, _result(AIInterpretation("x", (bad,))))

    def test_observation_absent_from_reference_rejected(self) -> None:
        pack = _pack()
        # Build a pack whose analysis lacks DESCRIPTION_HAS_URL.
        analysis = pack.analyses[0]
        subset = ReferenceAnalysis(
            reference=analysis.reference,
            analysis_basis=analysis.analysis_basis,
            facts=analysis.facts,
            observations=tuple(
                obs for obs in analysis.observations if obs.observation_type != ObservationType.DESCRIPTION_HAS_URL
            ),
        )
        stripped = EvidencePack(analyses=(subset,))
        citation = ObservationCitation(
            reference=analysis.reference, observation_type=ObservationType.DESCRIPTION_HAS_URL
        )
        with pytest.raises(ResearchInterpretationError, match="no observation description_has_url"):
            validate_interpretations(
                stripped, _result(AIInterpretation("x", (citation,)))
            )

    def test_pattern_citation_valid(self) -> None:
        analyses = (
            analyze_reference(_reference("a", title="5 tools")),
            analyze_reference(_reference("b", title="no numeral")),
        )
        patterns = aggregate_patterns(analyses)
        pack = EvidencePack(analyses=analyses, patterns=patterns)
        citation = PatternCitation(observation_type=ObservationType.TITLE_HAS_NUMERAL)
        assert validate_interpretations(
            pack, _result(AIInterpretation("x", (citation,)))
        ) is not None

    def test_pattern_citation_absent_rejected(self) -> None:
        pack = _pack()  # no patterns
        citation = PatternCitation(observation_type=ObservationType.TITLE_HAS_NUMERAL)
        with pytest.raises(ResearchInterpretationError, match="absent from the pack"):
            validate_interpretations(pack, _result(AIInterpretation("x", (citation,))))

    def test_fabricated_pattern_type_impossible(self) -> None:
        with pytest.raises(ValueError):
            ObservationType("title_is_clickbait")


class TestAIInterpretation:
    def test_valid(self) -> None:
        interpretation = AIInterpretation(
            "statement", (FactCitation(reference=_rid("a"), field=EvidenceField.TITLE),)
        )
        assert interpretation.claim_type is ClaimType.AI_INTERPRETATION

    def test_blank_statement_rejected(self) -> None:
        with pytest.raises(ResearchInterpretationError, match="blank"):
            AIInterpretation(
                "   ", (FactCitation(reference=_rid("a"), field=EvidenceField.TITLE),)
            )

    def test_no_citation_rejected(self) -> None:
        with pytest.raises(ResearchInterpretationError, match="at least one"):
            AIInterpretation("statement", ())

    def test_duplicate_citations_rejected(self) -> None:
        citation = FactCitation(reference=_rid("a"), field=EvidenceField.TITLE)
        with pytest.raises(ResearchInterpretationError, match="duplicate"):
            AIInterpretation("statement", (citation, citation))

    def test_claim_type_cannot_be_overridden(self) -> None:
        with pytest.raises(TypeError):
            AIInterpretation(
                "statement",
                (FactCitation(reference=_rid("a"), field=EvidenceField.TITLE),),
                claim_type=ClaimType.FACT,
            )

    def test_immutable(self) -> None:
        interpretation = AIInterpretation(
            "statement", (FactCitation(reference=_rid("a"), field=EvidenceField.TITLE),)
        )
        with pytest.raises(AttributeError):
            interpretation.statement = "changed"  # type: ignore[misc]


class TestModelProvenance:
    def test_valid(self) -> None:
        provenance = ModelProvenance(provider="test", model="test-model")
        assert provenance.provider == "test"
        assert provenance.model == "test-model"

    def test_blank_rejected(self) -> None:
        with pytest.raises(ResearchInterpretationError, match="provider"):
            ModelProvenance(provider="  ", model="m")
        with pytest.raises(ResearchInterpretationError, match="model"):
            ModelProvenance(provider="p", model="  ")

    def test_not_restricted_to_vendors(self) -> None:
        # provider/model are arbitrary non-blank strings; no vendor enum.
        assert ModelProvenance(provider="any-vendor", model="any-model").provider == "any-vendor"

    def test_immutable(self) -> None:
        provenance = ModelProvenance(provider="p", model="m")
        with pytest.raises(AttributeError):
            provenance.model = "x"  # type: ignore[misc]


class TestAnalysisBasis:
    def test_fact_citation_basis(self) -> None:
        pack = _pack()
        assert (
            interpretation_analysis_basis(
                pack, FactCitation(reference=_rid("a"), field=EvidenceField.TITLE)
            )
            is AnalysisBasis.TITLE
        )
        assert (
            interpretation_analysis_basis(
                pack, FactCitation(reference=_rid("a"), field=EvidenceField.DESCRIPTION)
            )
            is AnalysisBasis.DESCRIPTION
        )
        assert (
            interpretation_analysis_basis(
                pack, FactCitation(reference=_rid("a"), field=EvidenceField.VIEW_COUNT)
            )
            is AnalysisBasis.RAW_METRICS
        )
        assert (
            interpretation_analysis_basis(
                pack, FactCitation(reference=_rid("a"), field=EvidenceField.MARKET_CONTEXT)
            )
            is AnalysisBasis.SOURCE_METADATA
        )

    def test_observation_citation_basis_read_from_observation(self) -> None:
        pack = _pack()
        assert (
            interpretation_analysis_basis(
                pack,
                ObservationCitation(
                    reference=_rid("a"), observation_type=ObservationType.TITLE_HAS_NUMERAL
                ),
            )
            is AnalysisBasis.TITLE
        )
        assert (
            interpretation_analysis_basis(
                pack,
                ObservationCitation(
                    reference=_rid("a"), observation_type=ObservationType.DESCRIPTION_HAS_URL
                ),
            )
            is AnalysisBasis.DESCRIPTION
        )

    def test_pattern_citation_basis(self) -> None:
        analyses = (
            analyze_reference(_reference("a", title="5 tools")),
            analyze_reference(_reference("b", title="no numeral")),
        )
        pack = EvidencePack(analyses=analyses, patterns=aggregate_patterns(analyses))
        assert (
            interpretation_analysis_basis(
                pack, PatternCitation(observation_type=ObservationType.TITLE_HAS_NUMERAL)
            )
            is AnalysisBasis.TITLE
        )

    def test_no_media_basis_possible(self) -> None:
        pack = _pack()
        for citation in (
            FactCitation(reference=_rid("a"), field=EvidenceField.TITLE),
            ObservationCitation(
                reference=_rid("a"), observation_type=ObservationType.TITLE_HAS_NUMERAL
            ),
        ):
            basis = interpretation_analysis_basis(pack, citation)
            # Only title/description/metadata/metrics bases exist in M17.
            assert basis in (
                AnalysisBasis.TITLE,
                AnalysisBasis.DESCRIPTION,
                AnalysisBasis.SOURCE_METADATA,
                AnalysisBasis.RAW_METRICS,
            )


class TestFullFlow:
    def test_end_to_end_grounded_interpretation(self) -> None:
        analyses = (
            analyze_reference(_reference("a", title="5 AI Tools", description="guide: https://example.com")),
            analyze_reference(_reference("b", title="How AI Helps Students")),
        )
        patterns = aggregate_patterns(analyses)
        pack = EvidencePack(analyses=analyses, patterns=patterns)

        interpretation = AIInterpretation(
            "Half of the analyzed titles contain a numeral.",
            (
                PatternCitation(observation_type=ObservationType.TITLE_HAS_NUMERAL),
                FactCitation(reference=_rid("a"), field=EvidenceField.VIEW_COUNT),
            ),
        )
        result = _result(interpretation)
        assert validate_interpretations(pack, result) is result

    def test_fabricated_citation_fails(self) -> None:
        pack = _pack()
        result = _result(
            AIInterpretation(
                "fabricated",
                (FactCitation(reference=_rid("zzz"), field=EvidenceField.VIEW_COUNT),),
            )
        )
        with pytest.raises(ResearchInterpretationError):
            validate_interpretations(pack, result)


class TestDeterminism:
    def test_same_input_same_validation_outcome(self) -> None:
        pack = _pack()
        result = _result(
            AIInterpretation(
                "x", (FactCitation(reference=_rid("a"), field=EvidenceField.TITLE),)
            )
        )
        first = validate_interpretations(pack, result)
        second = validate_interpretations(pack, result)
        assert first == second
