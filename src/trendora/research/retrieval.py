"""Minimal structural retriever seam (M25C).

One protocol covering the operations ``ResearchRun`` and the application
service need. No connector framework, registry, factory hierarchy, or plugin
architecture. YouTube and Facebook retrievers both satisfy it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from trendora.research.models import ResearchQuery, ResearchReference


class ResearchRetriever(Protocol):
    """A source retriever: collect raw items, then normalize to references."""

    def collect(
        self,
        query: ResearchQuery,
        *,
        collected_at: datetime | None = None,
    ) -> object: ...

    def normalize(self, collected: object) -> tuple[ResearchReference, ...]: ...