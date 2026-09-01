"""HTTP request/response models for the V1 research API (M15).

Explicit serialization of the research domain. The domain stays authoritative:
``ResearchQuery`` validates semantics; these models only map HTTP values to and
from the domain. Enums serialize as stable strings; datetimes are timezone-aware
ISO 8601; no dataclass internals, ORM objects, or raw payloads are exposed.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from trendora.research.models import ResearchReference, ResearchRun


class ResearchRequest(BaseModel):
    """Structured research request body.

    ``sources`` maps to ``ResearchQuery.source_codes``. No semantic validation
    is duplicated here: blank topic, market validity, date range, source
    normalization, and result_limit bounds are enforced by ``ResearchQuery``.
    """

    topic: str
    market: str
    date_from: date
    date_to: date
    sources: list[str] = ["youtube"]
    result_limit: int = 50


class ResearchMetricsResponse(BaseModel):
    view_count: int | None
    like_count: int | None
    comment_count: int | None


class ResearchReferenceResponse(BaseModel):
    """Official source facts only (docs/16). No derived metrics or scores."""

    source_code: str
    content_external_id: str
    url: str | None
    title: str | None
    description: str | None
    published_at: datetime | None
    channel_external_id: str | None
    channel_title: str | None
    market_context: str | None
    market_basis: str | None
    source_rank: int | None
    metrics: ResearchMetricsResponse
    collected_at: datetime


class ResearchQueryResponse(BaseModel):
    topic: str
    market: str
    date_from: date
    date_to: date
    sources: list[str]
    result_limit: int


class SourceCoverageResponse(BaseModel):
    source_code: str
    capability: str
    status: str
    reason: str | None


class ResearchCoverageResponse(BaseModel):
    completeness: str
    sources: list[SourceCoverageResponse]


class ResearchResponse(BaseModel):
    """Top-level research result: query, coverage, execution truth, references."""

    query: ResearchQueryResponse
    coverage: ResearchCoverageResponse
    executed_sources: list[str]
    status: str
    references: list[ResearchReferenceResponse]


def to_research_response(run: ResearchRun) -> ResearchResponse:
    """Serialize a ``ResearchRun`` into the HTTP response model.

    Pure serialization only: no retrieval, no ranking, no derived metrics.
    ``executed_sources`` is execution truth from the run (sources actually
    attempted), distinct from requested sources and from capability coverage;
    it is populated even when a successful search returns zero references.
    """
    coverage = run.coverage
    assert coverage is not None
    references = run.references or ()
    return ResearchResponse(
        query=ResearchQueryResponse(
            topic=run.query.topic,
            market=run.query.market,
            date_from=run.query.date_from,
            date_to=run.query.date_to,
            sources=list(run.query.source_codes),
            result_limit=run.query.result_limit,
        ),
        coverage=ResearchCoverageResponse(
            completeness=coverage.completeness.value,
            sources=[
                SourceCoverageResponse(
                    source_code=item.source_code,
                    capability=item.capability.value,
                    status=item.status.value,
                    reason=item.reason.value if item.reason is not None else None,
                )
                for item in coverage.sources
            ],
        ),
        executed_sources=list(run.executed_sources),
        status=run.status.value,
        references=[_to_reference_response(reference) for reference in references],
    )


def _to_reference_response(reference: ResearchReference) -> ResearchReferenceResponse:
    return ResearchReferenceResponse(
        source_code=reference.source_code,
        content_external_id=reference.content_external_id,
        url=reference.url,
        title=reference.title,
        description=reference.description,
        published_at=reference.published_at,
        channel_external_id=reference.channel_external_id,
        channel_title=reference.channel_title,
        market_context=reference.market_context,
        market_basis=reference.market_basis.value if reference.market_basis is not None else None,
        source_rank=reference.source_rank,
        metrics=ResearchMetricsResponse(
            view_count=reference.metrics.view_count,
            like_count=reference.metrics.like_count,
            comment_count=reference.metrics.comment_count,
        ),
        collected_at=reference.collected_at,
    )
