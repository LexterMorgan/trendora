"""Research Core domain exceptions (M13).

In-memory research-domain errors. No network, no persistence.
"""


class ResearchError(Exception):
    """Base error for the research domain."""


class ResearchValidationError(ResearchError):
    """Invalid ResearchQuery or capability input."""


class ResearchStateError(ResearchError):
    """Invalid ResearchRun state transition."""
