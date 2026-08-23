"""In-memory series diagnostic contracts. Not ORM objects or scores."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID


class CadenceClass(StrEnum):
    """Factual gap-pattern label. Not a product regularity requirement.

    ``no_gap_data``: fewer than two observations, so no consecutive gaps.
    ``effectively_constant_cadence``: every consecutive gap is identical.
    ``variable_cadence``: at least two distinct consecutive-gap lengths.
    """

    NO_GAP_DATA = "no_gap_data"
    EFFECTIVELY_CONSTANT = "effectively_constant_cadence"
    VARIABLE = "variable_cadence"


class MonotonicityClass(StrEnum):
    """Factual consecutive-value label. Not a cumulative-metric registry.

    ``no_delta_data``: fewer than two observations.
    ``constant``: every consecutive delta is 0.
    ``non_decreasing``: every delta >= 0 and at least one delta > 0.
    ``non_increasing``: every delta <= 0 and at least one delta < 0.
    ``mixed``: at least one positive delta and at least one negative delta.
    """

    NO_DELTA_DATA = "no_delta_data"
    CONSTANT = "constant"
    NON_DECREASING = "non_decreasing"
    NON_INCREASING = "non_increasing"
    MIXED = "mixed"


@dataclass(frozen=True)
class SeriesDiagnostics:
    """Deterministic description of one M5 MetricSeries.

    Not a forecastability score, model recommendation, or product decision.
    """

    source_code: str | None
    metric_name: str | None
    observation_count: int
    gap_count: int
    zero_gap_count: int
    unique_gap_count: int
    gaps_differing_from_median_count: int
    duplicate_observed_at_group_count: int
    duplicate_observed_at_observation_count: int
    duplicate_observed_at_conflicting_value_group_count: int
    duplicate_observed_at_groups_resolved_by_collected_at: int
    duplicate_observed_at_groups_with_tied_collected_at: int
    delta_count: int
    positive_delta_count: int
    negative_delta_count: int
    zero_delta_count: int
    total_positive_movement: int
    total_negative_movement: int
    cadence: CadenceClass
    monotonicity: MonotonicityClass
    origin: str
    first_observed_at: datetime | None = None
    last_observed_at: datetime | None = None
    elapsed_duration: timedelta | None = None
    min_gap: timedelta | None = None
    max_gap: timedelta | None = None
    mean_gap: timedelta | None = None
    median_gap: timedelta | None = None
    gap_coefficient_of_variation: float | None = None
    min_delta: int | None = None
    max_delta: int | None = None
    mean_delta: float | None = None
    mean_absolute_delta: float | None = None
    max_absolute_delta: int | None = None
    stdev_delta: float | None = None
    fraction_non_decreasing: float | None = None
    fraction_decreasing: float | None = None
    fraction_flat: float | None = None
    content_item_id: UUID | None = None
    publisher_id: UUID | None = None
