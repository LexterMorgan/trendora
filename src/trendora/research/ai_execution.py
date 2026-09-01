"""Grounded interpretation execution service (M20).

Smallest orchestration: run the provider, then run MANDATORY M19 grounding
validation. No bypass. The service does not perform research, build references,
run M17/M18, query databases, or touch APIs/frontends — it starts from an
existing valid ``EvidencePack``.
"""

from __future__ import annotations

from trendora.research.ai_provider import AIInterpretationProvider
from trendora.research.interpretation import (
    EvidencePack,
    InterpretationResult,
    validate_interpretations,
)


class GroundedInterpretationService:
    """Executes a provider and only returns M19-grounded interpretations."""

    def __init__(self, provider: AIInterpretationProvider) -> None:
        self._provider = provider

    def interpret(self, pack: EvidencePack) -> InterpretationResult:
        """Provider output, then mandatory grounding validation."""
        result = self._provider.interpret(pack)
        return validate_interpretations(pack, result)
