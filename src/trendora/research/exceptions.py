"""Research Core domain exceptions (M13).

In-memory research-domain errors. No network, no persistence.
"""


class ResearchError(Exception):
    """Base error for the research domain."""


class ResearchValidationError(ResearchError):
    """Invalid ResearchQuery or capability input."""


class ResearchStateError(ResearchError):
    """Invalid ResearchRun state transition."""


class ResearchNoCoverageError(ResearchError):
    """No requested source can satisfy the required capability (run is blocked)."""


class ResearchSourceNotConfiguredError(ResearchError):
    """A source supports the capability but no runtime retriever is configured."""


class ResearchAggregationError(ResearchError):
    """Malformed input to pattern aggregation (duplicates, invalid values)."""


class ResearchInterpretationError(ResearchError):
    """Invalid AI-interpretation input or ungrounded citations."""


class ResearchAIProviderNotConfiguredError(ResearchError):
    """Required AI provider runtime configuration is missing or incomplete."""


class ResearchAIProviderError(ResearchError):
    """Upstream provider failure (network, timeout, non-2xx HTTP)."""


class ResearchAIResponseError(ResearchError):
    """Malformed provider/model response or invalid model output."""
