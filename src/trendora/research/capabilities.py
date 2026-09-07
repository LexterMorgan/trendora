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

# Canonical source codes for research resolution: persisted SOURCE_IDS plus
# the in-memory-only "facebook" source. Facebook persistence remains deferred
# (no SOURCE_IDS / seed / migration changes; Meta approval/access still owed).
KNOWN_SOURCE_CODES: Final[frozenset[str]] = frozenset({*SOURCE_IDS, "facebook"})


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
        "facebook": SourceCapabilities(
            source_code="facebook",
            supported=frozenset(
                {
                    PlatformCapability.CREATOR_WATCHLIST,
                    PlatformCapability.PUBLIC_METRICS,
                    PlatformCapability.CONTENT_TEXT_AVAILABLE,
                }
            ),
            retention_note=(
                "Facebook public Page posts only; no keyword search or "
                "regional discovery; Meta approval/access still required."
            ),
        ),
    }


def required_capability_for_source(source_code: str) -> PlatformCapability:
    """The one capability required to execute one requested source.

    Topic-based public content discovery (YouTube/HN/SE/GitHub) requires
    ``public_search``; Facebook's explicit single-Page mode requires
    ``creator_watchlist``. Resolution is per source — never a cross-product
    of every capability against every source.
    """
    if source_code == "facebook":
        return PlatformCapability.CREATOR_WATCHLIST
    return PlatformCapability.PUBLIC_SEARCH


def required_capabilities(query: ResearchQuery) -> tuple[PlatformCapability, ...]:
    """Distinct capabilities required by a ResearchQuery, in request order.

    Derived from ``required_capability_for_source`` so single- and
    combined-source queries share one rule set.
    """
    capabilities: list[PlatformCapability] = []
    for source_code in query.source_codes:
        capability = required_capability_for_source(source_code)
        if capability not in capabilities:
            capabilities.append(capability)
    return tuple(capabilities)
