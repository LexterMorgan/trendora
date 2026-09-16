"""Public web search retrieval interface (M36A).

One provider (Serper) implements this. The interface stays minimal: search and
cleanup. No multi-provider orchestration, no scraping.

``SearchResult.url`` is guaranteed to be an absolute HTTP(S) URL: the gateway
drops any provider entry that fails the safe-URL boundary, so a result without
a valid URL never exists.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class SearchResult(BaseModel):
    """One validated indexed public web result. No engagement metrics exist."""

    url: str
    title: str = ""
    snippet: str = ""
    domain: str = ""


class WebSearchRetriever(Protocol):
    """A public web search backend."""

    def search(self, query: str, *, limit: int = 15) -> list[SearchResult]: ...

    def close(self) -> None: ...
