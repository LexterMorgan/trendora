"""Minimal connector protocol. Future sources add implementations; they do not belong here."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ChannelIngestionOutcome:
    """Result of ingesting one watchlist identity."""

    external_id: str
    publisher_created: bool = False
    publisher_updated: bool = False
    content_items_upserted: int = 0
    snapshots_inserted: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class IngestionResult:
    """Summary of one connector run. Safe to log; contains no secrets."""

    source_code: str
    watchlist_size: int
    outcomes: list[ChannelIngestionOutcome] = field(default_factory=list)

    @property
    def succeeded(self) -> list[ChannelIngestionOutcome]:
        return [row for row in self.outcomes if row.ok]

    @property
    def failed(self) -> list[ChannelIngestionOutcome]:
        return [row for row in self.outcomes if not row.ok]

    @property
    def snapshots_inserted(self) -> int:
        return sum(row.snapshots_inserted for row in self.succeeded)

    @property
    def content_items_upserted(self) -> int:
        return sum(row.content_items_upserted for row in self.succeeded)


class Connector(Protocol):
    """Source-agnostic ingestion entry. Implementations must not share HTTP clients."""

    source_code: str

    def ingest(self) -> IngestionResult:
        """Fetch, normalize, and persist the connector's configured watchlist."""
        ...
