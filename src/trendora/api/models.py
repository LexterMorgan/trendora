"""Pydantic response models for the V1 forecast API.

Field names mirror the M10 ``GitHubForecastResult`` contract (docs/13 §6).
``interval`` is a Python ``timedelta`` in M10 and is exposed here as the
whole-day integer ``interval_days`` (docs/13 §11). Enums serialize as their
stable ``.value`` strings. Datetimes are timezone-aware ISO 8601.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from trendora.product.github_forecast import GitHubForecastResult

_SECONDS_PER_DAY = 86400


class ForecastPointResponse(BaseModel):
    """One Trendora-generated forecast point (docs/13 §7)."""

    at: datetime
    value: float


class ForecastResponse(BaseModel):
    """HTTP representation of the M10 GitHub forecast product result."""

    source_code: str
    metric_name: str
    content_item_id: UUID
    content_external_id: str | None
    model: str
    horizon: int
    interval_days: int
    origin: str
    observation_count: int
    history_start: datetime
    history_end: datetime
    latest_observed_at: datetime
    cadence: str
    irregular_cadence: bool
    points: list[ForecastPointResponse]


def to_forecast_response(result: GitHubForecastResult) -> ForecastResponse:
    """Serialize an M10 ``GitHubForecastResult`` into the API response model.

    Pure serialization only: no forecast mathematics, no resampling, no
    timestamp generation. Timestamps and values come from M10 unchanged.
    """

    return ForecastResponse(
        source_code=result.source_code,
        metric_name=result.metric_name,
        content_item_id=result.content_item_id,
        content_external_id=result.content_external_id,
        model=result.model.value,
        horizon=result.horizon,
        interval_days=int(result.interval.total_seconds() // _SECONDS_PER_DAY),
        origin=result.origin,
        observation_count=result.observation_count,
        history_start=result.history_start,
        history_end=result.history_end,
        latest_observed_at=result.latest_observed_at,
        cadence=result.cadence.value,
        irregular_cadence=result.irregular_cadence,
        points=[ForecastPointResponse(at=point.at, value=point.value) for point in result.points],
    )
