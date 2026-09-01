"""M17 evidence facts and content observations tests. Pure, deterministic."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from trendora.research import (
    AnalysisBasis,
    ClaimType,
    ContentObservation,
    EvidenceFact,
    EvidenceField,
    MarketBasis,
    ObservationType,
    ReferenceAnalysis,
    ReferenceId,
    ResearchMetrics,
    ResearchReference,
    analyze_reference,
    analyze_references,
    extract_evidence,
    reference_id,
)

UTC = timezone.utc
COLLECTED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
PUBLISHED_AT = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)


def _reference(**overrides) -> ResearchReference:
    payload = dict(
        source_code="youtube",
        content_external_id="video1",
        collected_at=COLLECTED_AT,
        url="https://www.youtube.com/watch?v=video1",
        title="5 AI Tools for Students?",
        description="Full guide: https://example.com/guide",
        published_at=PUBLISHED_AT,
        channel_external_id="UCx",
        channel_title="Example Channel",
        market_context="SG",
        market_basis=MarketBasis.YOUTUBE_REGION_AVAILABILITY,
        source_rank=3,
        metrics=ResearchMetrics(view_count=100000, like_count=None, comment_count=120),
    )
    payload.update(overrides)
    return ResearchReference(**payload)


def _facts(reference: ResearchReference) -> dict[EvidenceField, EvidenceFact]:
    return {fact.field: fact for fact in extract_evidence(reference)}


def _obs_by_type(analysis: ReferenceAnalysis) -> dict[ObservationType, ContentObservation]:
    return {obs.observation_type: obs for obs in analysis.observations}


class TestEvidenceFacts:
    def test_source_fields_preserved_exactly(self) -> None:
        facts = _facts(_reference())
        assert facts[EvidenceField.TITLE].value == "5 AI Tools for Students?"
        assert facts[EvidenceField.DESCRIPTION].value == "Full guide: https://example.com/guide"
        assert facts[EvidenceField.URL].value == "https://www.youtube.com/watch?v=video1"
        assert facts[EvidenceField.CHANNEL_TITLE].value == "Example Channel"
        assert facts[EvidenceField.PUBLISHED_AT].value == PUBLISHED_AT
        assert facts[EvidenceField.SOURCE_RANK].value == 3
        assert facts[EvidenceField.MARKET_CONTEXT].value == "SG"
        assert facts[EvidenceField.MARKET_BASIS].value == "youtube_region_availability"

    def test_raw_metrics_preserved(self) -> None:
        facts = _facts(_reference())
        assert facts[EvidenceField.VIEW_COUNT].value == 100000
        assert facts[EvidenceField.LIKE_COUNT].value is None
        assert facts[EvidenceField.COMMENT_COUNT].value == 120

    def test_missing_metric_stays_none_not_zero(self) -> None:
        facts = _facts(_reference())
        assert facts[EvidenceField.LIKE_COUNT].value is None
        assert facts[EvidenceField.VIEW_COUNT].value == 100000

    def test_zero_stays_zero(self) -> None:
        facts = _facts(_reference(metrics=ResearchMetrics(view_count=0, like_count=0, comment_count=0)))
        assert facts[EvidenceField.VIEW_COUNT].value == 0
        assert facts[EvidenceField.LIKE_COUNT].value == 0

    def test_facts_are_fact_claim_type(self) -> None:
        for fact in extract_evidence(_reference()):
            assert fact.claim_type is ClaimType.FACT

    def test_fact_ordering_deterministic(self) -> None:
        first = [f.field for f in extract_evidence(_reference())]
        second = [f.field for f in extract_evidence(_reference())]
        assert first == second
        assert first == list(EvidenceField)


class TestTemporalProvenance:
    def test_collected_at_preserved_exactly(self) -> None:
        facts = _facts(_reference())
        fact = facts[EvidenceField.COLLECTED_AT]
        assert fact.value == COLLECTED_AT
        assert fact.value == _reference().collected_at
        assert fact.value.tzinfo is not None

    def test_no_generated_analysis_timestamp(self) -> None:
        reference = _reference()
        analysis = analyze_reference(reference)
        datetime_values = {
            fact.value for fact in analysis.facts if isinstance(fact.value, datetime)
        }
        # Only the reference's own source timestamps appear; nothing generated.
        assert datetime_values == {reference.published_at, reference.collected_at}


class TestClaimTypeStructural:
    def test_evidence_fact_claim_type_cannot_be_overridden(self) -> None:
        with pytest.raises(TypeError):
            EvidenceFact(
                reference=ReferenceId("youtube", "video1"),
                field=EvidenceField.TITLE,
                value="x",
                claim_type=ClaimType.OBSERVATION,
            )

    def test_content_observation_claim_type_cannot_be_overridden(self) -> None:
        with pytest.raises(TypeError):
            ContentObservation(
                reference=ReferenceId("youtube", "video1"),
                observation_type=ObservationType.TITLE_HAS_NUMERAL,
                value=True,
                evidence_fields=(EvidenceField.TITLE,),
                analysis_basis=AnalysisBasis.TITLE,
                claim_type=ClaimType.FACT,
            )

    def test_claim_types_are_structural_and_immutable(self) -> None:
        reference = _reference()
        analysis = analyze_reference(reference)
        assert all(fact.claim_type is ClaimType.FACT for fact in analysis.facts)
        assert all(obs.claim_type is ClaimType.OBSERVATION for obs in analysis.observations)
        with pytest.raises(AttributeError):
            analysis.facts[0].claim_type = ClaimType.OBSERVATION  # type: ignore[misc]


class TestObservations:
    def test_title_character_count(self) -> None:
        analysis = analyze_reference(_reference(title="abc"))
        assert _obs_by_type(analysis)[ObservationType.TITLE_CHARACTER_COUNT].value == 3

    def test_title_character_count_empty_title(self) -> None:
        analysis = analyze_reference(_reference(title=None))
        assert _obs_by_type(analysis)[ObservationType.TITLE_CHARACTER_COUNT].value == 0

    def test_title_has_numeral(self) -> None:
        assert _obs_by_type(analyze_reference(_reference(title="5 tools")))[
            ObservationType.TITLE_HAS_NUMERAL
        ].value is True
        assert _obs_by_type(analyze_reference(_reference(title="no numerals")))[
            ObservationType.TITLE_HAS_NUMERAL
        ].value is False

    def test_title_has_numeral_unicode_digit(self) -> None:
        analysis = analyze_reference(_reference(title="\u0665 tools"))  # Arabic-Indic 5
        assert _obs_by_type(analysis)[ObservationType.TITLE_HAS_NUMERAL].value is True

    def test_title_has_question_mark_half_and_full_width(self) -> None:
        assert _obs_by_type(analyze_reference(_reference(title="Why?")))[
            ObservationType.TITLE_HAS_QUESTION_MARK
        ].value is True
        assert _obs_by_type(analyze_reference(_reference(title="Why\uff1f")))[
            ObservationType.TITLE_HAS_QUESTION_MARK
        ].value is True
        assert _obs_by_type(analyze_reference(_reference(title="Plain title")))[
            ObservationType.TITLE_HAS_QUESTION_MARK
        ].value is False

    def test_description_present(self) -> None:
        assert _obs_by_type(analyze_reference(_reference(description="Some text")))[
            ObservationType.DESCRIPTION_PRESENT
        ].value is True
        assert _obs_by_type(analyze_reference(_reference(description="   ")))[
            ObservationType.DESCRIPTION_PRESENT
        ].value is False
        assert _obs_by_type(analyze_reference(_reference(description=None)))[
            ObservationType.DESCRIPTION_PRESENT
        ].value is False

    def test_description_character_count(self) -> None:
        assert _obs_by_type(analyze_reference(_reference(description="abcd")))[
            ObservationType.DESCRIPTION_CHARACTER_COUNT
        ].value == 4
        assert _obs_by_type(analyze_reference(_reference(description=None)))[
            ObservationType.DESCRIPTION_CHARACTER_COUNT
        ].value == 0

    def test_description_has_url(self) -> None:
        assert _obs_by_type(analyze_reference(_reference(description="see http://example.com")))[
            ObservationType.DESCRIPTION_HAS_URL
        ].value is True
        assert _obs_by_type(analyze_reference(_reference(description="see https://example.com")))[
            ObservationType.DESCRIPTION_HAS_URL
        ].value is True
        assert _obs_by_type(analyze_reference(_reference(description="no url here")))[
            ObservationType.DESCRIPTION_HAS_URL
        ].value is False
        # bare www. is NOT detected; only explicit http(s):// scheme.
        assert _obs_by_type(analyze_reference(_reference(description="visit www.example.com")))[
            ObservationType.DESCRIPTION_HAS_URL
        ].value is False


class TestProvenance:
    def test_every_observation_has_evidence_and_basis(self) -> None:
        for obs in analyze_reference(_reference()).observations:
            assert len(obs.evidence_fields) >= 1
            assert obs.analysis_basis in AnalysisBasis
            assert obs.claim_type is ClaimType.OBSERVATION

    def test_title_observations_cite_title_only(self) -> None:
        analysis = analyze_reference(_reference())
        for obs in analysis.observations:
            if obs.observation_type in (
                ObservationType.TITLE_CHARACTER_COUNT,
                ObservationType.TITLE_HAS_NUMERAL,
                ObservationType.TITLE_HAS_QUESTION_MARK,
            ):
                assert obs.evidence_fields == (EvidenceField.TITLE,)
                assert obs.analysis_basis is AnalysisBasis.TITLE

    def test_description_observations_cite_description_only(self) -> None:
        analysis = analyze_reference(_reference())
        for obs in analysis.observations:
            if obs.observation_type in (
                ObservationType.DESCRIPTION_PRESENT,
                ObservationType.DESCRIPTION_CHARACTER_COUNT,
                ObservationType.DESCRIPTION_HAS_URL,
            ):
                assert obs.evidence_fields == (EvidenceField.DESCRIPTION,)
                assert obs.analysis_basis is AnalysisBasis.DESCRIPTION

    def test_no_observation_claims_media_basis(self) -> None:
        for obs in analyze_reference(_reference()).observations:
            # M17 only ever uses TITLE or DESCRIPTION basis.
            assert obs.analysis_basis in (AnalysisBasis.TITLE, AnalysisBasis.DESCRIPTION)

    def test_reference_identity_attached(self) -> None:
        analysis = analyze_reference(_reference())
        assert analysis.reference == ReferenceId("youtube", "video1")
        for fact in analysis.facts:
            assert fact.reference == analysis.reference
        for obs in analysis.observations:
            assert obs.reference == analysis.reference

    def test_identity_matches_reference(self) -> None:
        reference = _reference()
        assert reference_id(reference) == ReferenceId("youtube", "video1")


class TestNegativeGuarantees:
    def test_no_aggregation(self) -> None:
        analyses = analyze_references([_reference(), _reference(content_external_id="video2")])
        assert len(analyses) == 2
        # Each analysis is per-reference; no cross-reference counts exist.
        for analysis in analyses:
            assert len(analysis.observations) == 6
            assert analysis.reference.content_external_id in ("video1", "video2")

    def test_observation_vocabulary_is_closed_and_small(self) -> None:
        # Structurally: only the six deterministic metadata observations exist.
        assert {obs.value for obs in ObservationType} == {
            "title_character_count",
            "title_has_numeral",
            "title_has_question_mark",
            "description_present",
            "description_character_count",
            "description_has_url",
        }

    def test_no_performance_or_derived_metrics(self) -> None:
        analysis = analyze_reference(_reference())
        # Observations carry no scores; only deterministic structural facts.
        for obs in analysis.observations:
            assert obs.value in (True, False) or isinstance(obs.value, int)

    def test_market_no_country_inference(self) -> None:
        # No country/language evidence field exists structurally.
        forbidden = {
            "creator_country",
            "publisher_country",
            "origin_country",
            "language",
        }
        assert not ({field.value for field in EvidenceField} & forbidden)
        facts = _facts(_reference())
        assert facts[EvidenceField.MARKET_CONTEXT].value == "SG"
        assert facts[EvidenceField.MARKET_BASIS].value == "youtube_region_availability"

    def test_no_transcript_or_media_fields(self) -> None:
        forbidden = {
            "transcript",
            "spoken_hook",
            "visual_hook",
            "scene",
            "sentiment",
            "audience_demographic",
        }
        assert not ({field.value for field in EvidenceField} & forbidden)
        assert not ({basis.value for basis in AnalysisBasis} & {"transcript", "audio", "video", "image"})


class TestImmutabilityDeterminism:
    def test_analysis_is_immutable(self) -> None:
        analysis = analyze_reference(_reference())
        with pytest.raises(AttributeError):
            analysis.observations = ()  # type: ignore[misc]
        with pytest.raises(AttributeError):
            analysis.facts[0].value = "changed"  # type: ignore[misc]

    def test_observation_and_fact_are_frozen(self) -> None:
        fact = EvidenceFact(
            reference=ReferenceId("youtube", "video1"),
            field=EvidenceField.TITLE,
            value="x",
        )
        with pytest.raises(AttributeError):
            fact.value = "y"  # type: ignore[misc]
        obs = ContentObservation(
            reference=ReferenceId("youtube", "video1"),
            observation_type=ObservationType.TITLE_HAS_NUMERAL,
            value=True,
            evidence_fields=(EvidenceField.TITLE,),
            analysis_basis=AnalysisBasis.TITLE,
        )
        with pytest.raises(AttributeError):
            obs.value = False  # type: ignore[misc]

    def test_deterministic_same_input_same_output(self) -> None:
        reference = _reference()
        first = analyze_reference(reference)
        second = analyze_reference(reference)
        assert first == second
        assert extract_evidence(reference) == extract_evidence(reference)

    def test_reference_not_mutated(self) -> None:
        reference = _reference()
        before = (reference.title, reference.metrics.view_count)
        analyze_reference(reference)
        assert (reference.title, reference.metrics.view_count) == before
