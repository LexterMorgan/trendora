"""M18 deterministic pattern aggregation tests. Pure, deterministic."""

from __future__ import annotations

import pytest

from trendora.research import (
    AnalysisBasis,
    ContentObservation,
    EvidenceField,
    ObservationType,
    PatternAggregate,
    ReferenceAnalysis,
    ReferenceId,
    ResearchAggregationError,
    aggregate_patterns,
    analyze_reference,
    analyze_references,
)
from trendora.research.patterns import BOOLEAN_OBSERVATION_TYPES


def _obs(
    rid: ReferenceId,
    obs_type: ObservationType,
    value: bool,
) -> ContentObservation:
    return ContentObservation(
        reference=rid,
        observation_type=obs_type,
        value=value,
        evidence_fields=(EvidenceField.TITLE,),
        analysis_basis=AnalysisBasis.TITLE,
    )


def _analysis(rid: ReferenceId, observations: list[ContentObservation]) -> ReferenceAnalysis:
    return ReferenceAnalysis(
        reference=rid,
        analysis_basis=(AnalysisBasis.TITLE,),
        facts=(),
        observations=tuple(observations),
    )


def _rid(source: str, external: str) -> ReferenceId:
    return ReferenceId(source_code=source, content_external_id=external)


def _by_type(aggregates: tuple[PatternAggregate, ...]) -> dict[ObservationType, PatternAggregate]:
    return {a.observation_type: a for a in aggregates}


class TestBooleanAggregation:
    def test_all_true(self) -> None:
        aggregates = aggregate_patterns(
            [
                _analysis(_rid("youtube", "a"), [_obs(_rid("youtube", "a"), ObservationType.TITLE_HAS_NUMERAL, True)]),
                _analysis(_rid("youtube", "b"), [_obs(_rid("youtube", "b"), ObservationType.TITLE_HAS_NUMERAL, True)]),
            ]
        )
        agg = _by_type(aggregates)[ObservationType.TITLE_HAS_NUMERAL]
        assert agg.analyzed_count == 2
        assert agg.matching_count == 2
        assert agg.non_matching_count == 0
        assert agg.ratio == 1.0

    def test_all_false(self) -> None:
        aggregates = aggregate_patterns(
            [
                _analysis(_rid("youtube", "a"), [_obs(_rid("youtube", "a"), ObservationType.TITLE_HAS_QUESTION_MARK, False)]),
                _analysis(_rid("youtube", "b"), [_obs(_rid("youtube", "b"), ObservationType.TITLE_HAS_QUESTION_MARK, False)]),
            ]
        )
        agg = _by_type(aggregates)[ObservationType.TITLE_HAS_QUESTION_MARK]
        assert agg.matching_count == 0
        assert agg.non_matching_count == 2
        assert agg.ratio == 0.0

    def test_mixed_true_false(self) -> None:
        aggregates = aggregate_patterns(
            [
                _analysis(_rid("youtube", "a"), [_obs(_rid("youtube", "a"), ObservationType.TITLE_HAS_NUMERAL, True)]),
                _analysis(_rid("youtube", "b"), [_obs(_rid("youtube", "b"), ObservationType.TITLE_HAS_NUMERAL, True)]),
                _analysis(_rid("youtube", "c"), [_obs(_rid("youtube", "c"), ObservationType.TITLE_HAS_NUMERAL, False)]),
            ]
        )
        agg = _by_type(aggregates)[ObservationType.TITLE_HAS_NUMERAL]
        assert agg.analyzed_count == 3
        assert agg.matching_count == 2
        assert agg.non_matching_count == 1
        assert agg.ratio == pytest.approx(2 / 3)

    def test_one_reference(self) -> None:
        aggregates = aggregate_patterns(
            [_analysis(_rid("youtube", "a"), [_obs(_rid("youtube", "a"), ObservationType.DESCRIPTION_PRESENT, True)])]
        )
        agg = _by_type(aggregates)[ObservationType.DESCRIPTION_PRESENT]
        assert agg.analyzed_count == 1
        assert agg.matching_count == 1
        assert agg.ratio == 1.0

    def test_empty_input_returns_empty(self) -> None:
        assert aggregate_patterns([]) == ()

    def test_matching_reference_ids_preserved_in_order(self) -> None:
        aggregates = aggregate_patterns(
            [
                _analysis(_rid("youtube", "b"), [_obs(_rid("youtube", "b"), ObservationType.TITLE_HAS_NUMERAL, True)]),
                _analysis(_rid("youtube", "a"), [_obs(_rid("youtube", "a"), ObservationType.TITLE_HAS_NUMERAL, False)]),
                _analysis(_rid("youtube", "c"), [_obs(_rid("youtube", "c"), ObservationType.TITLE_HAS_NUMERAL, True)]),
            ]
        )
        agg = _by_type(aggregates)[ObservationType.TITLE_HAS_NUMERAL]
        assert agg.matching_reference_ids == (
            _rid("youtube", "b"),
            _rid("youtube", "c"),
        )
        assert agg.non_matching_reference_ids == (_rid("youtube", "a"),)

    def test_consumes_real_m17_analysis(self) -> None:
        from trendora.research.evidence import analyze_reference
        from trendora.research.models import MarketBasis, ResearchMetrics, ResearchReference
        from datetime import datetime, timezone

        def reference(external: str, title: str) -> ResearchReference:
            return ResearchReference(
                source_code="youtube",
                content_external_id=external,
                collected_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                url=f"https://www.youtube.com/watch?v={external}",
                title=title,
                description="has https://example.com link",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                market_context="SG",
                market_basis=MarketBasis.YOUTUBE_REGION_AVAILABILITY,
                source_rank=1,
                metrics=ResearchMetrics(view_count=10, like_count=None, comment_count=1),
            )

        analyses = analyze_references(
            [reference("a", "5 tools"), reference("b", "no numeral"), reference("c", "10 ways")]
        )
        aggregates = aggregate_patterns(analyses)
        agg = _by_type(aggregates)[ObservationType.TITLE_HAS_NUMERAL]
        assert agg.analyzed_count == 3
        assert agg.matching_count == 2
        assert agg.ratio == pytest.approx(2 / 3)


class TestMissingObservations:
    def test_missing_observation_not_treated_as_false(self) -> None:
        # 'b' has no TITLE_HAS_QUESTION_MARK observation.
        aggregates = aggregate_patterns(
            [
                _analysis(_rid("youtube", "a"), [_obs(_rid("youtube", "a"), ObservationType.TITLE_HAS_QUESTION_MARK, True)]),
                _analysis(_rid("youtube", "b"), [_obs(_rid("youtube", "b"), ObservationType.TITLE_HAS_NUMERAL, True)]),
            ]
        )
        agg = _by_type(aggregates)[ObservationType.TITLE_HAS_QUESTION_MARK]
        assert agg.analyzed_count == 1
        assert agg.non_matching_count == 0
        assert agg.matching_reference_ids == (_rid("youtube", "a"),)

    def test_absent_observation_type_produces_no_aggregate(self) -> None:
        aggregates = aggregate_patterns(
            [_analysis(_rid("youtube", "a"), [_obs(_rid("youtube", "a"), ObservationType.TITLE_HAS_NUMERAL, True)])]
        )
        assert ObservationType.DESCRIPTION_HAS_URL not in _by_type(aggregates)


class TestDuplicates:
    def test_duplicate_reference_id_rejected(self) -> None:
        with pytest.raises(ResearchAggregationError, match="duplicate reference"):
            aggregate_patterns(
                [
                    _analysis(_rid("youtube", "a"), [_obs(_rid("youtube", "a"), ObservationType.TITLE_HAS_NUMERAL, True)]),
                    _analysis(_rid("youtube", "a"), [_obs(_rid("youtube", "a"), ObservationType.TITLE_HAS_NUMERAL, False)]),
                ]
            )

    def test_duplicate_observation_type_in_analysis_rejected(self) -> None:
        rid = _rid("youtube", "a")
        with pytest.raises(ResearchAggregationError, match="duplicate title_has_numeral"):
            aggregate_patterns(
                [
                    _analysis(
                        rid,
                        [
                            _obs(rid, ObservationType.TITLE_HAS_NUMERAL, True),
                            _obs(rid, ObservationType.TITLE_HAS_NUMERAL, False),
                        ],
                    )
                ]
            )


class TestTypeSafety:
    def test_non_boolean_value_rejected(self) -> None:
        rid = _rid("youtube", "a")
        malformed = ContentObservation(
            reference=rid,
            observation_type=ObservationType.TITLE_HAS_NUMERAL,
            value=1,
            evidence_fields=(EvidenceField.TITLE,),
            analysis_basis=AnalysisBasis.TITLE,
        )
        with pytest.raises(ResearchAggregationError, match="must be boolean"):
            aggregate_patterns([_analysis(rid, [malformed])])


class TestImmutabilityDeterminism:
    def test_aggregate_is_immutable(self) -> None:
        aggregates = aggregate_patterns(
            [_analysis(_rid("youtube", "a"), [_obs(_rid("youtube", "a"), ObservationType.TITLE_HAS_NUMERAL, True)])]
        )
        with pytest.raises(AttributeError):
            aggregates[0].matching_count = 99  # type: ignore[misc]

    def test_deterministic_same_input_same_output(self) -> None:
        analyses = [
            _analysis(_rid("youtube", "a"), [_obs(_rid("youtube", "a"), ObservationType.TITLE_HAS_NUMERAL, True)]),
            _analysis(_rid("youtube", "b"), [_obs(_rid("youtube", "b"), ObservationType.TITLE_HAS_NUMERAL, False)]),
        ]
        assert aggregate_patterns(analyses) == aggregate_patterns(analyses)

    def test_input_not_mutated(self) -> None:
        analyses = [
            _analysis(_rid("youtube", "a"), [_obs(_rid("youtube", "a"), ObservationType.TITLE_HAS_NUMERAL, True)])
        ]
        before = analyses[0].observations
        aggregate_patterns(analyses)
        assert analyses[0].observations == before

    def test_deterministic_order_follows_enum(self) -> None:
        aggregates = aggregate_patterns(
            [
                _analysis(
                    _rid("youtube", "a"),
                    [
                        _obs(_rid("youtube", "a"), ObservationType.DESCRIPTION_HAS_URL, True),
                        _obs(_rid("youtube", "a"), ObservationType.TITLE_HAS_NUMERAL, True),
                    ],
                )
            ]
        )
        # Only present observation types are emitted, in enum declaration order.
        assert [a.observation_type for a in aggregates] == [
            ObservationType.TITLE_HAS_NUMERAL,
            ObservationType.DESCRIPTION_HAS_URL,
        ]


class TestNegativeGuarantees:
    def test_only_boolean_observation_types_supported(self) -> None:
        assert {t.value for t in BOOLEAN_OBSERVATION_TYPES} == {
            "title_has_numeral",
            "title_has_question_mark",
            "description_present",
            "description_has_url",
        }

    def test_aggregate_has_no_performance_fields(self) -> None:
        aggregates = aggregate_patterns(
            [_analysis(_rid("youtube", "a"), [_obs(_rid("youtube", "a"), ObservationType.TITLE_HAS_NUMERAL, True)])]
        )
        fields = {f.name for f in PatternAggregate.__dataclass_fields__.values()}
        assert not (fields & {"success_rate", "confidence", "performance", "effectiveness"})
        for aggregate in aggregates:
            assert aggregate.ratio is not None and 0.0 <= aggregate.ratio <= 1.0

    def test_no_ids_or_timestamps_in_aggregate(self) -> None:
        aggregates = aggregate_patterns(
            [_analysis(_rid("youtube", "a"), [_obs(_rid("youtube", "a"), ObservationType.TITLE_HAS_NUMERAL, True)])]
        )
        fields = {f.name for f in PatternAggregate.__dataclass_fields__.values()}
        assert "id" not in fields
        assert "created_at" not in fields
        assert "generated_at" not in fields
