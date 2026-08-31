"""Static source capability declarations and the query->capability mapping (M13).

Declarations are in-memory and immutable. They describe what a platform CAN
support (docs/14 section 9), not credentials, runtime configuration, temporary
errors, or authorization state. A future connector may register its own
declaration without changing ``ResearchQuery``.
"""

from __future__ import annotations

from typing import Final

from trendora.reference import SOURCE_IDS

from trendora.research.models import (
    PlatformCapability,
    ResearchQuery,
    SourceCapabilities,
)

# Canonical source codes from the existing source registry (reference.py).
# Capabilities belong to these canonical sources; no pseudo-sources are created.
KNOWN_SOURCE_CODES: Final[frozenset[str]] = frozenset(SOURCE_IDS)


def default_declarations() -> dict[str, SourceCapabilities]:
    """Static capability declarations for the four research-relevant sources.

    Other canonical sources (wikimedia, gdelt) are intentionally not declared:
    they are known sources with no research capability claim, so any research
    capability requested against them resolves to ``capability_not_supported``.
    """
    return {
        "youtube": SourceCapabilities(
            source_code="youtube",
            supported=frozenset(
                {
                    PlatformCapability.PUBLIC_SEARCH,
                    PlatformCapability.CREATOR_WATCHLIST,
                    PlatformCapability.CONTENT_LOOKUP,
                    PlatformCapability.REGIONAL_DISCOVERY,
                    PlatformCapability.PUBLIC_METRICS,
                    PlatformCapability.CONTENT_TEXT_AVAILABLE,
                }
            ),
            conditional=frozenset({PlatformCapability.OWNED_ACCOUNT_METRICS}),
            retention_note=(
                "YouTube non-authorized statistics/metadata: 30-day "
                "refresh-or-delete unless an analytics storage amendment is "
                "approved (docs/03)."
            ),
        ),
        "hacker_news": SourceCapabilities(
            source_code="hacker_news",
            supported=frozenset(
                {
                    PlatformCapability.CONTENT_LOOKUP,
                    PlatformCapability.CREATOR_WATCHLIST,
                    PlatformCapability.PUBLIC_METRICS,
                    PlatformCapability.CONTENT_TEXT_AVAILABLE,
                }
            ),
        ),
        "stack_exchange": SourceCapabilities(
            source_code="stack_exchange",
            supported=frozenset(
                {
                    PlatformCapability.PUBLIC_SEARCH,
                    PlatformCapability.CONTENT_LOOKUP,
                    PlatformCapability.PUBLIC_METRICS,
                    PlatformCapability.CONTENT_TEXT_AVAILABLE,
                }
            ),
        ),
        "github": SourceCapabilities(
            source_code="github",
            supported=frozenset(
                {
                    PlatformCapability.CONTENT_LOOKUP,
                    PlatformCapability.CREATOR_WATCHLIST,
                    PlatformCapability.PUBLIC_METRICS,
                }
            ),
        ),
    }


def required_capabilities(query: ResearchQuery) -> tuple[PlatformCapability, ...]:
    """Capabilities required to execute a ResearchQuery.

    V1 (M13): topic-based public content discovery requires ``public_search``.
    Future query shapes (watchlist, owned-account) add their own mappings here.
    """
    return (PlatformCapability.PUBLIC_SEARCH,)
