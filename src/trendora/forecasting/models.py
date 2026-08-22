"""In-memory forecast contracts. These are not ORM objects or pandas types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from trendora.analytics.repository import ObservationQuery


class ForecastModel(StrEnum):
    NAIVE = "naive"
    MOVING_AVERAGE = "moving_average"
    SIMPLE_EXPONENTIAL_SMOOTHING = "simple_exponential_smoothing"


@dataclass(frozen=True)
class ForecastRequest:
    """Forecast over an M5 query. Interval is explicit; never inferred from history."""

    query: ObservationQuery
    model: ForecastModel
    horizon: int
    interval: timedelta
    window: int | None = None
    alpha: float | None = None


@dataclass(frozen=True)
class EvaluationRequest:
    """Chronological holdout evaluation. ``holdout`` is the test observation count."""

    query: ObservationQuery
    model: ForecastModel
    holdout: int
    interval: timedelta
    window: int | None = None
    alpha: float | None = None


@dataclass(frozen=True)
class ForecastPoint:
    at: datetime
    value: float


@dataclass(frozen=True)
class ForecastResult:
    source_code: str
    metric_name: str
    model: ForecastModel
    interval: timedelta
    horizon: int
    origin: str
    history_start: datetime
    history_end: datetime
    history_count: int
    points: tuple[ForecastPoint, ...]
    content_item_id: UUID | None = None
    publisher_id: UUID | None = None


@dataclass(frozen=True)
class EvaluationResult:
    model: ForecastModel
    training_observation_count: int
    test_observation_count: int
    mae: float
    holdout_start: datetime
    holdout_end: datetime
    origin: str


@dataclass(frozen=True)
class ComparisonRequest:
    """Naive vs one M6A challenger on the same M5 series and holdout.

    Not a production model-selection decision.
    """

    query: ObservationQuery
    challenger: ForecastModel
    holdout: int
    interval: timedelta
    window: int | None = None
    alpha: float | None = None


@dataclass(frozen=True)
class ComparisonResult:
    source_code: str
    metric_name: str
    holdout: int
    interval: timedelta
    challenger: ForecastModel
    naive_mae: float
    challenger_mae: float
    training_observation_count: int
    test_observation_count: int
    holdout_start: datetime
    holdout_end: datetime
    challenger_beats_naive: bool
    origin: str
    content_item_id: UUID | None = None
    publisher_id: UUID | None = None
