"""Deterministic pattern aggregation over ReferenceAnalysis (M18).

Aggregates boolean M17 ``ContentObservation`` values across a collection of
``ReferenceAnalysis`` into immutable ``PatternAggregate`` objects. Pure
deterministic aggregation of observation occurrence only: no performance
comparison, no engagement, no ranking, no content gaps, no recommendations,
no AI.

Consumes M17 observations directly; never reconstructs observations from raw
``ResearchReference`` text (M17 owns detection semantics).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from trendora.research.exceptions import ResearchAggregationError
from trendora.research.evidence import (
    ObservationType,
    ReferenceAnalysis,
    ReferenceId,
)

# ObservationType in this set are boolean-valued in M17.
BOOLEAN_OBSERVATION_TYPES: tuple[ObservationType, ...] = (
    ObservationType.TITLE_HAS_NUMERAL,
    ObservationType.TITLE_HAS_QUESTION_MARK,
    ObservationType.DESCRIPTION_PRESENT,
    ObservationType.DESCRIPTION_HAS_URL,
)


@dataclass(frozen=True, slots=True)
class PatternAggregate:
    """Deterministic prevalence of one boolean observation across analyses.

    ``analyzed_count`` is the number of references that actually contain this
    observation (missing observation is not counted and is not false).
    ``ratio`` is ``matching_count / analyzed_count`` in [0.0, 1.0], a
    descriptive prevalence, never a performance/effectiveness/confidence
    value. Reference identities preserve input order.
    """

    observation_type: ObservationType
    analyzed_count: int
    matching_count: int
    non_matching_count: int
    ratio: float
    matching_reference_ids: tuple[ReferenceId, ...]
    non_matching_reference_ids: tuple[ReferenceId, ...]


def aggregate_patterns(
    analyses: Sequence[ReferenceAnalysis],
) -> tuple[PatternAggregate, ...]:
    """Aggregate boolean observations across analyses (deterministic order).

    Empty input returns an empty tuple. Only observation types that actually
    appear are emitted. Raises ``ResearchAggregationError`` on duplicate
    ``ReferenceId`` values, duplicate observations of the same type within one
    analysis, or non-boolean observation values.
    """
    _reject_duplicate_references(analyses)
    aggregates: list[PatternAggregate] = []
    for observation_type in BOOLEAN_OBSERVATION_TYPES:
        aggregate = _aggregate_boolean(analyses, observation_type)
        if aggregate is not None:
            aggregates.append(aggregate)
    return tuple(aggregates)


def _aggregate_boolean(
    analyses: Sequence[ReferenceAnalysis],
    observation_type: ObservationType,
) -> PatternAggregate | None:
    matching: list[ReferenceId] = []
    non_matching: list[ReferenceId] = []
    for analysis in analyses:
        observations = [
            obs for obs in analysis.observations if obs.observation_type is observation_type
        ]
        if len(observations) > 1:
            raise ResearchAggregationError(
                f"analysis for {analysis.reference} has duplicate "
                f"{observation_type.value} observations"
            )
        if not observations:
            continue  # missing observation: not counted, not false
        value = observations[0].value
        if not isinstance(value, bool):
            raise ResearchAggregationError(
                f"{observation_type.value} value must be boolean; got {value!r}"
            )
        if value:
            matching.append(analysis.reference)
        else:
            non_matching.append(analysis.reference)

    analyzed_count = len(matching) + len(non_matching)
    if analyzed_count == 0:
        return None
    return PatternAggregate(
        observation_type=observation_type,
        analyzed_count=analyzed_count,
        matching_count=len(matching),
        non_matching_count=len(non_matching),
        ratio=len(matching) / analyzed_count,
        matching_reference_ids=tuple(matching),
        non_matching_reference_ids=tuple(non_matching),
    )


def _reject_duplicate_references(analyses: Sequence[ReferenceAnalysis]) -> None:
    seen: set[ReferenceId] = set()
    for analysis in analyses:
        if analysis.reference in seen:
            raise ResearchAggregationError(
                f"duplicate reference in aggregation input: {analysis.reference}"
            )
        seen.add(analysis.reference)
