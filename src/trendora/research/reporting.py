"""Backend research report pipeline (M23A).

Composes existing M15–M22 seams into one truthful structured report:

    ResearchApplicationService → completed ResearchRun → analyze_references →
    aggregate_patterns → EvidencePack → GroundedInterpretationService →
    InterpretationResult → StrategicContext → GroundedStrategyService →
    StrategicResult → IdeationContext → GroundedIdeationService →
    IdeationResult → ResearchReport

No new intelligence, no fourth AI call, no workflow engine. Retrieval, evidence
construction, and every AI stage normally run exactly once. The one exception:
an AI stage that fails with ``ResearchAIResponseError`` (malformed/unvalidatable
model output) is retried at most once — maximum two attempts for that stage —
without rerunning retrieval, evidence construction, or any other AI stage. Any
other failure (provider errors, timeouts, configuration, grounding/domain
errors) propagates and is never converted to empty output.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import TypeVar

from trendora.connectors.facebook.client import FacebookPublicClient
from trendora.connectors.youtube.client import YouTubeClient
from trendora.research.ai_execution import GroundedInterpretationService
from trendora.research.ai_provider import (
    AIProviderConfig,
    OpenAICompatibleInterpretationProvider,
)
from trendora.research.application import (
    ResearchApplicationService,
    build_research_application_service,
)
from trendora.research.evidence import EvidenceField, analyze_references, reference_id
from trendora.research.exceptions import (
    ResearchAIResponseError,
    ResearchInterpretationError,
    ResearchNoCoverageError,
)
from trendora.research.ideation import (
    GroundedIdeationService,
    IdeationContext,
    IdeationResult,
    OpenAICompatibleIdeationProvider,
    validate_ideation_result,
)
from trendora.research.interpretation import (
    EvidencePack,
    InterpretationResult,
    validate_interpretations,
)
from trendora.research.models import ResearchRun, ResearchRunStatus
from trendora.research.patterns import aggregate_patterns
from trendora.research.strategy import (
    GroundedStrategyService,
    OpenAICompatibleStrategyProvider,
    StrategicContext,
    StrategicResult,
    validate_strategic_result,
)

logger = logging.getLogger("trendora.research.reporting")

_T = TypeVar("_T")


class ResearchReportStatus(StrEnum):
    """Outcome of a report. Distinct from ``ResearchRun.status``."""

    COMPLETED = "completed"
    NO_EVIDENCE = "no_evidence"


@dataclass(frozen=True, slots=True)
class ResearchReport:
    """Structured report of one research request through ideation."""

    status: ResearchReportStatus
    research_run: ResearchRun
    evidence_pack: EvidencePack | None
    interpretation_result: InterpretationResult | None
    strategic_result: StrategicResult | None
    ideation_result: IdeationResult | None


def validate_research_report(report: ResearchReport) -> ResearchReport:
    """Validate report invariants; return unchanged or raise.

    Structural grounding is preserved: it does not prove semantic entailment.
    """
    run = report.research_run
    if run.status is not ResearchRunStatus.COMPLETED:
        raise ResearchInterpretationError("report requires a completed research run")
    if not run.executed_sources:
        raise ResearchInterpretationError("report requires executed retrieval")
    if report.status is ResearchReportStatus.NO_EVIDENCE:
        _validate_no_evidence(report)
        return report
    if report.status is ResearchReportStatus.COMPLETED:
        _validate_completed(report)
        return report
    raise ResearchInterpretationError(f"unknown report status {report.status}")


def _validate_no_evidence(report: ResearchReport) -> None:
    run = report.research_run
    if run.references != ():
        raise ResearchInterpretationError("no_evidence report must have zero references")
    for name, value in (
        ("evidence_pack", report.evidence_pack),
        ("interpretation_result", report.interpretation_result),
        ("strategic_result", report.strategic_result),
        ("ideation_result", report.ideation_result),
    ):
        if value is not None:
            raise ResearchInterpretationError(
                f"no_evidence report must have null {name}"
            )


def _validate_completed(report: ResearchReport) -> None:
    run = report.research_run
    references = run.references or ()
    if not references:
        raise ResearchInterpretationError("completed report requires nonempty references")
    pack = report.evidence_pack
    interpretation = report.interpretation_result
    strategic = report.strategic_result
    ideation = report.ideation_result
    if pack is None or interpretation is None or strategic is None or ideation is None:
        raise ResearchInterpretationError(
            "completed report requires all downstream stages present"
        )
    for reference in references:
        if not reference.url or not reference.url.strip():
            raise ResearchInterpretationError(
                "completed report requires a nonblank original URL for every reference"
            )

    _validate_pack_identity(pack, references)
    validate_interpretations(pack, interpretation)
    _require_provenance(interpretation.model_provenance, "interpretation")
    _require_provenance(strategic.model_provenance, "strategy")
    _require_provenance(ideation.model_provenance, "ideation")

    strategic_context = StrategicContext(
        evidence_pack=pack,
        interpretation_result=interpretation,
    )
    validate_strategic_result(strategic_context, strategic)
    ideation_context = IdeationContext(
        strategic_context=strategic_context,
        strategic_result=strategic,
    )
    validate_ideation_result(ideation_context, ideation)


def _validate_pack_identity(pack: EvidencePack, references) -> None:
    if len(pack.analyses) != len(references):
        raise ResearchInterpretationError(
            "evidence pack analyses must exactly match the completed run references"
        )
    for analysis, reference in zip(pack.analyses, references, strict=True):
        if analysis.reference != reference_id(reference):
            raise ResearchInterpretationError(
                "evidence pack reference identity does not match the research run"
            )
        url_fact = next(
            (fact.value for fact in analysis.facts if fact.field is EvidenceField.URL),
            None,
        )
        if url_fact != reference.url:
            raise ResearchInterpretationError(
                "evidence pack URL fact does not match the reference URL"
            )


def _require_provenance(provenance, stage: str) -> None:
    if provenance is None or not provenance.provider or not provenance.model:
        raise ResearchInterpretationError(
            f"{stage} result requires trusted model provenance"
        )


class ResearchReportService:
    """Synchronous report orchestration. No workflow engine."""

    def __init__(
        self,
        research: ResearchApplicationService,
        interpretation: GroundedInterpretationService,
        strategy: GroundedStrategyService,
        ideation: GroundedIdeationService,
    ) -> None:
        self._research = research
        self._interpretation = interpretation
        self._strategy = strategy
        self._ideation = ideation

    def _run_ai_stage(self, stage: str, call: Callable[[], _T]) -> _T:
        """Run one AI stage; retry at most once on malformed provider output.

        Only ``ResearchAIResponseError`` (strict parse/validation failure of
        the model response) is retried, for a maximum of two attempts. All
        other errors propagate unchanged. Logs carry only the stage name and
        exception class — never response bodies, evidence, or credentials.
        """
        try:
            return call()
        except ResearchAIResponseError as exc:
            logger.warning(
                "research.report.ai_retry stage=%s error=%s", stage, type(exc).__name__
            )
            return call()

    def build_report(
        self,
        *,
        topic: str,
        market: str,
        date_from: date,
        date_to: date,
        sources,
        result_limit: int,
        facebook_page_id: str | None = None,
    ) -> ResearchReport:
        run = self._research.execute(
            topic=topic,
            market=market,
            date_from=date_from,
            date_to=date_to,
            sources=sources,
            result_limit=result_limit,
            facebook_page_id=facebook_page_id,
        )
        if run.status is ResearchRunStatus.BLOCKED:
            raise ResearchNoCoverageError(
                "no requested source can satisfy the required capability"
            )
        if run.status is not ResearchRunStatus.COMPLETED:
            raise ResearchNoCoverageError("research run did not complete")

        references = run.references or ()
        if not references:
            report = ResearchReport(
                status=ResearchReportStatus.NO_EVIDENCE,
                research_run=run,
                evidence_pack=None,
                interpretation_result=None,
                strategic_result=None,
                ideation_result=None,
            )
            return validate_research_report(report)

        analyses = analyze_references(references)
        patterns = aggregate_patterns(analyses)
        pack = EvidencePack(analyses=analyses, patterns=patterns)

        interpretation_result = self._run_ai_stage(
            "interpretation", lambda: self._interpretation.interpret(pack)
        )
        strategic_context = StrategicContext(
            evidence_pack=pack,
            interpretation_result=interpretation_result,
        )
        strategic_result = self._run_ai_stage(
            "strategy", lambda: self._strategy.generate(strategic_context)
        )
        ideation_context = IdeationContext(
            strategic_context=strategic_context,
            strategic_result=strategic_result,
        )
        ideation_result = self._run_ai_stage(
            "ideation", lambda: self._ideation.generate(ideation_context)
        )

        report = ResearchReport(
            status=ResearchReportStatus.COMPLETED,
            research_run=run,
            evidence_pack=pack,
            interpretation_result=interpretation_result,
            strategic_result=strategic_result,
            ideation_result=ideation_result,
        )
        return validate_research_report(report)


def build_research_report_service(
    *,
    youtube_client: YouTubeClient | None,
    facebook_client: FacebookPublicClient | None = None,
    http_client,
    config: AIProviderConfig,
) -> ResearchReportService:
    """Wire the report service from our clients + one shared HTTP client."""
    research = build_research_application_service(
        youtube_client=youtube_client,
        facebook_client=facebook_client,
    )
    interpretation = GroundedInterpretationService(
        OpenAICompatibleInterpretationProvider(config, http_client=http_client)
    )
    strategy = GroundedStrategyService(
        OpenAICompatibleStrategyProvider(config, http_client=http_client)
    )
    ideation = GroundedIdeationService(
        OpenAICompatibleIdeationProvider(config, http_client=http_client)
    )
    return ResearchReportService(research, interpretation, strategy, ideation)
