"""Deterministic in-memory diagnostics over M5 MetricSeries."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from statistics import mean, median, stdev
from uuid import UUID

from trendora.analytics.models import MetricObservation, MetricSeries, ordered_observations
from trendora.analytics.repository import ObservationQuery
from trendora.analytics.service import AnalyticsService
from trendora.diagnostics.exceptions import DiagnosticsValidationError
from trendora.diagnostics.models import CadenceClass, MonotonicityClass, SeriesDiagnostics

_ORIGIN = "trendora_diagnostic"


class DiagnosticsService:
    """Describes M5 series. Does not query metric_snapshots, forecast, or write."""

    def __init__(self, analytics: AnalyticsService) -> None:
        self._analytics = analytics

    def diagnose(self, query: ObservationQuery) -> SeriesDiagnostics:
        series = self._analytics.get_metric_series(query)
        return diagnose_series(series)


def diagnose_series(series: MetricSeries) -> SeriesDiagnostics:
    ordered = _aware_ordered(series)
    gaps = _gaps(ordered)
    deltas = _deltas(ordered)
    duplicate = _duplicate_observed_at(ordered)
    content_item_id, publisher_id = _subject_ids(ordered)
    first = ordered[0].observed_at if ordered else None
    last = ordered[-1].observed_at if ordered else None
    elapsed = (last - first) if first is not None and last is not None else None
    return SeriesDiagnostics(
        source_code=series.source_code,
        metric_name=series.metric_name,
        observation_count=len(ordered),
        first_observed_at=first,
        last_observed_at=last,
        elapsed_duration=elapsed,
        gap_count=len(gaps),
        min_gap=min(gaps) if gaps else None,
        max_gap=max(gaps) if gaps else None,
        mean_gap=_mean_timedelta(gaps),
        median_gap=_median_timedelta(gaps),
        zero_gap_count=sum(1 for gap in gaps if gap == timedelta(0)),
        unique_gap_count=len(set(gaps)),
        gaps_differing_from_median_count=_gaps_differing_from_median(gaps),
        gap_coefficient_of_variation=_coefficient_of_variation_seconds(gaps),
        cadence=_cadence(gaps),
        duplicate_observed_at_group_count=duplicate["group_count"],
        duplicate_observed_at_observation_count=duplicate["observation_count"],
        duplicate_observed_at_conflicting_value_group_count=duplicate["conflicting_value_groups"],
        duplicate_observed_at_groups_resolved_by_collected_at=duplicate["resolved_by_collected_at"],
        duplicate_observed_at_groups_with_tied_collected_at=duplicate["tied_collected_at"],
        delta_count=len(deltas),
        positive_delta_count=sum(1 for delta in deltas if delta > 0),
        negative_delta_count=sum(1 for delta in deltas if delta < 0),
        zero_delta_count=sum(1 for delta in deltas if delta == 0),
        min_delta=min(deltas) if deltas else None,
        max_delta=max(deltas) if deltas else None,
        mean_delta=mean(deltas) if deltas else None,
        mean_absolute_delta=mean(abs(delta) for delta in deltas) if deltas else None,
        max_absolute_delta=max(abs(delta) for delta in deltas) if deltas else None,
        stdev_delta=stdev(deltas) if len(deltas) >= 2 else None,
        monotonicity=_monotonicity(deltas),
        fraction_non_decreasing=_fraction(deltas, lambda delta: delta >= 0),
        fraction_decreasing=_fraction(deltas, lambda delta: delta < 0),
        fraction_flat=_fraction(deltas, lambda delta: delta == 0),
        total_positive_movement=sum(delta for delta in deltas if delta > 0),
        total_negative_movement=abs(sum(delta for delta in deltas if delta < 0)),
        origin=_ORIGIN,
        content_item_id=content_item_id,
        publisher_id=publisher_id,
    )


def _aware_ordered(series: MetricSeries) -> tuple[MetricObservation, ...]:
    ordered = ordered_observations(series.observations)
    for row in ordered:
        if row.observed_at.tzinfo is None or row.collected_at.tzinfo is None:
            raise DiagnosticsValidationError("observation timestamps must be timezone-aware")
    return ordered


def _gaps(ordered: tuple[MetricObservation, ...]) -> list[timedelta]:
    return [ordered[i].observed_at - ordered[i - 1].observed_at for i in range(1, len(ordered))]


def _deltas(ordered: tuple[MetricObservation, ...]) -> list[int]:
    return [ordered[i].metric_value - ordered[i - 1].metric_value for i in range(1, len(ordered))]


def _mean_timedelta(gaps: list[timedelta]) -> timedelta | None:
    if not gaps:
        return None
    return timedelta(seconds=mean(gap.total_seconds() for gap in gaps))


def _median_timedelta(gaps: list[timedelta]) -> timedelta | None:
    if not gaps:
        return None
    return timedelta(seconds=median(gap.total_seconds() for gap in gaps))


def _gaps_differing_from_median(gaps: list[timedelta]) -> int:
    if not gaps:
        return 0
    middle = _median_timedelta(gaps)
    assert middle is not None
    return sum(1 for gap in gaps if gap != middle)


def _coefficient_of_variation_seconds(values: list[timedelta]) -> float | None:
    if len(values) < 2:
        return None
    seconds = [item.total_seconds() for item in values]
    center = mean(seconds)
    if center == 0:
        return None
    return stdev(seconds) / center


def _cadence(gaps: list[timedelta]) -> CadenceClass:
    if not gaps:
        return CadenceClass.NO_GAP_DATA
    if len(set(gaps)) == 1:
        return CadenceClass.EFFECTIVELY_CONSTANT
    return CadenceClass.VARIABLE


def _monotonicity(deltas: list[int]) -> MonotonicityClass:
    if not deltas:
        return MonotonicityClass.NO_DELTA_DATA
    if all(delta == 0 for delta in deltas):
        return MonotonicityClass.CONSTANT
    if all(delta >= 0 for delta in deltas):
        return MonotonicityClass.NON_DECREASING
    if all(delta <= 0 for delta in deltas):
        return MonotonicityClass.NON_INCREASING
    return MonotonicityClass.MIXED


def _fraction(deltas: list[int], predicate) -> float | None:
    if not deltas:
        return None
    return sum(1 for delta in deltas if predicate(delta)) / len(deltas)


def _duplicate_observed_at(ordered: tuple[MetricObservation, ...]) -> dict[str, int]:
    groups: dict[object, list[MetricObservation]] = defaultdict(list)
    for row in ordered:
        groups[row.observed_at].append(row)
    duplicates = [rows for rows in groups.values() if len(rows) > 1]
    conflicting = 0
    resolved = 0
    tied = 0
    for rows in duplicates:
        if len({row.metric_value for row in rows}) > 1:
            conflicting += 1
        collected = {row.collected_at for row in rows}
        if len(collected) == len(rows):
            resolved += 1
        if len(collected) == 1:
            tied += 1
    return {
        "group_count": len(duplicates),
        "observation_count": sum(len(rows) for rows in duplicates),
        "conflicting_value_groups": conflicting,
        "resolved_by_collected_at": resolved,
        "tied_collected_at": tied,
    }


def _subject_ids(
    ordered: tuple[MetricObservation, ...],
) -> tuple[UUID | None, UUID | None]:
    content_ids = {row.content_item_id for row in ordered if row.content_item_id is not None}
    publisher_ids = {row.publisher_id for row in ordered if row.publisher_id is not None}
    content_item_id = next(iter(content_ids)) if len(content_ids) == 1 else None
    publisher_id = next(iter(publisher_ids)) if len(publisher_ids) == 1 else None
    return content_item_id, publisher_id
