"""Research reports with optional, structurally grounded content generation.

Explicit research mode synthesizes evidence with the existing interpretation
adapter and falls back to bounded source quotations. Omitting the content
flag preserves the legacy three-stage pipeline and snapshot representation.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import TypeVar

import httpx

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
from trendora.research.deadline import AIPhaseDeadline, call_with_deadline
from trendora.research.run_details import measure_stage, record_retry
from trendora.research.evidence import EvidenceField, analyze_references, reference_id
from trendora.research.exceptions import (
    ResearchAIResponseError,
    ResearchAIProviderError,
    ResearchAIProviderNotConfiguredError,
    ResearchAITimeoutError,
    ResearchInterpretationError,
    ResearchNoCoverageError,
)
from trendora.research.ai_input import build_interpretation_input
from trendora.research.ideation import (
    GroundedIdeationService,
    IdeationContext,
    IdeationResult,
    OpenAICompatibleIdeationProvider,
    validate_ideation_result,
)
from trendora.research.interpretation import (
    EvidencePack,
    AIInterpretation,
    FactCitation,
    InterpretationResult,
    ModelProvenance,
    validate_interpretations,
    validate_research_synthesis,
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
    RESEARCH_COMPLETED = "research_completed"
    CONTENT_UNAVAILABLE = "content_unavailable"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    RESEARCH_UNAVAILABLE = "research_unavailable"


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
    if report.status in (
        ResearchReportStatus.COMPLETED,
        ResearchReportStatus.RESEARCH_COMPLETED,
        ResearchReportStatus.CONTENT_UNAVAILABLE,
        ResearchReportStatus.INSUFFICIENT_EVIDENCE,
        ResearchReportStatus.RESEARCH_UNAVAILABLE,
    ):
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
    if pack is None:
        raise ResearchInterpretationError("research report requires evidence")
    if report.status is ResearchReportStatus.COMPLETED and (
        interpretation is None or strategic is None or ideation is None
    ):
        raise ResearchInterpretationError(
            "completed report requires all downstream stages present"
        )
    for reference in references:
        if not reference.url or not reference.url.strip():
            raise ResearchInterpretationError(
                "completed report requires a nonblank original URL for every reference"
            )

    _validate_pack_identity(pack, references)
    if interpretation is None:
        if report.status is not ResearchReportStatus.RESEARCH_UNAVAILABLE:
            raise ResearchInterpretationError("research report requires findings")
        if strategic is not None or ideation is not None:
            raise ResearchInterpretationError("content requires research findings")
        return
    validate_interpretations(pack, interpretation)
    _require_provenance(interpretation.model_provenance, "interpretation")
    if report.status is ResearchReportStatus.INSUFFICIENT_EVIDENCE:
        if interpretation.interpretations or strategic is not None or ideation is not None:
            raise ResearchInterpretationError("insufficient evidence cannot contain findings or content")
    if interpretation.model_provenance.provider == "source_evidence":
        if interpretation != source_summaries(pack):
            raise ResearchInterpretationError("source summaries must match cited source excerpts")
    if strategic is None:
        if ideation is not None:
            raise ResearchInterpretationError("ideation requires strategy")
        return
    _require_provenance(strategic.model_provenance, "strategy")

    strategic_context = StrategicContext(
        evidence_pack=pack,
        interpretation_result=interpretation,
    )
    validate_strategic_result(strategic_context, strategic)
    if ideation is None:
        return
    _require_provenance(ideation.model_provenance, "ideation")
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
        for field, text in ((EvidenceField.TITLE, reference.title), (EvidenceField.DESCRIPTION, reference.description)):
            value = next((fact.value for fact in analysis.facts if fact.field is field), None)
            if value != text:
                raise ResearchInterpretationError("evidence text does not match the collected reference")


def _require_provenance(provenance, stage: str) -> None:
    if provenance is None or not provenance.provider or not provenance.model:
        raise ResearchInterpretationError(
            f"{stage} result requires trusted model provenance"
        )


def source_excerpt(text: str) -> str:
    excerpt = text.strip()[:300]
    if len(text.strip()) > 300 and " " in excerpt:
        excerpt = excerpt.rsplit(" ", 1)[0]
    return excerpt


def source_summaries(pack: EvidencePack) -> InterpretationResult:
    """Concise, exact source excerpts; no event or semantic inference.

The reader attributes each quotation and labels its publication-window scope.
Descriptions/snippets are preferred to titles and never treated as full text.
"""
    items = []
    for analysis in pack.analyses:
        for field in (EvidenceField.DESCRIPTION, EvidenceField.TITLE):
            text = next((fact.value for fact in analysis.facts if fact.field is field), None)
            if not isinstance(text, str) or not text.strip():
                continue
            excerpt = source_excerpt(text)
            items.append(AIInterpretation(excerpt, (FactCitation(analysis.reference, field),)))
            break
    return validate_interpretations(pack, InterpretationResult(
        model_provenance=ModelProvenance(provider="source_evidence", model="extractive-v1"),
        interpretations=tuple(items),
    ))


class ResearchReportService:
    """Synchronous report orchestration. No workflow engine."""

    def __init__(
        self,
        research: ResearchApplicationService,
        interpretation: GroundedInterpretationService | None = None,
        strategy: GroundedStrategyService | None = None,
        ideation: GroundedIdeationService | None = None,
        ai_phase_budget_seconds: float | None = None,
    ) -> None:
        self._research = research
        self._interpretation = interpretation
        self._strategy = strategy
        self._ideation = ideation
        # Shared monotonic budget for the whole AI phase (interpretation +
        # retry + optional strategy/ideation). ``None`` preserves prior
        # behavior (no shared deadline) for callers that do not set it.
        self._ai_phase_budget_seconds = ai_phase_budget_seconds

    def _ai_deadline(self) -> "AIPhaseDeadline | None":
        if self._ai_phase_budget_seconds is None:
            return None
        return AIPhaseDeadline(self._ai_phase_budget_seconds)

    def _run_ai_stage(
        self,
        stage: str,
        call: Callable[[], _T],
        deadline: "AIPhaseDeadline | None" = None,
    ) -> _T:
        """Run one AI stage; retry at most once on malformed provider output.

        Only ``ResearchAIResponseError`` (strict parse/validation failure of
        the model response) is retried, for a maximum of two attempts. All
        other errors propagate unchanged. Logs carry only the stage name and
        exception class — never response bodies, evidence, or credentials.

        The retry shares the caller's ``deadline``: it never restarts the
        budget. If the budget is already exhausted, no retry is attempted and
        the original malformed-output error is re-raised so the caller's
        labeled fallback still applies.
        """
        with measure_stage(stage):
            try:
                return call()
            except ResearchAIResponseError as exc:
                if deadline is not None and deadline.expired():
                    logger.warning(
                        "research.report.ai_retry_skipped stage=%s reason=budget_exhausted",
                        stage,
                    )
                    raise
                logger.warning(
                    "research.report.ai_retry stage=%s error=%s reason=%s",
                    stage,
                    type(exc).__name__,
                    getattr(exc, "reason_code", "unspecified"),
                )
                record_retry()
                return call()

    def build_report(
        self,
        *,
        topic: str,
        market: str | None = None,
        markets=None,
        date_from: date,
        date_to: date,
        sources,
        result_limit: int,
        facebook_page_id: str | None = None,
        include_content_tools: bool | None = None,
    ) -> ResearchReport:
        with measure_stage("collection"):
            run = self._research.execute(
                topic=topic,
                market=market,
                markets=markets,
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
        pack = EvidencePack(
            analyses=analyses, patterns=patterns,
            research_query=run.query if include_content_tools is not None else None,
        )

        if include_content_tools is not None:
            # One shared budget for the whole AI phase: interpretation + its
            # malformed-output retry + optional strategy/ideation. Collection
            # has already run; persistence follows outside this budget.
            deadline = self._ai_deadline()
            interpretation_result = source_summaries(pack)
            strategic_result = None
            ideation_result = None
            status = ResearchReportStatus.RESEARCH_COMPLETED
            if not interpretation_result.interpretations:
                status = ResearchReportStatus.INSUFFICIENT_EVIDENCE
            else:
                try:
                    if self._interpretation is None:
                        raise ResearchAIProviderNotConfiguredError("interpretation provider is unavailable")
                    # The model sees a compact, diverse subset of the same
                    # evidence; it can cite only what it was given. The report's
                    # stored pack below is unchanged.
                    interpretation_input = build_interpretation_input(pack)
                    synthesis = self._run_ai_stage(
                        "interpretation",
                        lambda: call_with_deadline(
                            self._interpretation.interpret, interpretation_input, deadline
                        ),
                        deadline,
                    )
                    # Research-synthesis boundary: a finding must rest on real
                    # source text (title/description), not on sample-shape
                    # patterns, observations, or metrics. Rejection falls back to
                    # labelled excerpts with no extra AI work.
                    validate_research_synthesis(interpretation_input, synthesis)
                    interpretation_result = synthesis
                except (
                    ResearchAIProviderError, ResearchAIProviderNotConfiguredError,
                    ResearchAIResponseError, ResearchInterpretationError,
                ) as exc:
                    # Log the exact class and rejection reason so a timeout is
                    # distinguishable from a connection/non-2xx failure, and a
                    # truncated or invalid response from a bound violation,
                    # without exposing provider text.
                    logger.warning(
                        "research.report.interpretation_unavailable error=%s reason=%s",
                        type(exc).__name__,
                        getattr(exc, "reason_code", "unspecified"),
                    )
            if interpretation_result.interpretations and include_content_tools:
                try:
                    if self._strategy is None or self._ideation is None:
                        raise ResearchAIProviderNotConfiguredError("content provider is unavailable")
                    # Optional stages share the same remaining budget.
                    if deadline is not None and deadline.expired():
                        raise ResearchAITimeoutError("AI phase budget exhausted before content tools")
                    context = StrategicContext(pack, interpretation_result)
                    strategic_result = self._run_ai_stage(
                        "strategy",
                        lambda: call_with_deadline(
                            self._strategy.generate, context, deadline
                        ),
                        deadline,
                    )
                    # Validate before passing any provider output to another stage.
                    validate_strategic_result(context, strategic_result)
                    ideation_context = IdeationContext(context, strategic_result)
                    ideation_result = self._run_ai_stage(
                        "ideation",
                        lambda: call_with_deadline(
                            self._ideation.generate, ideation_context, deadline
                        ),
                        deadline,
                    )
                    validate_ideation_result(ideation_context, ideation_result)
                except (
                    ResearchAIProviderError, ResearchAIProviderNotConfiguredError,
                    ResearchAIResponseError, ResearchInterpretationError,
                ) as exc:
                    logger.warning("research.report.content_unavailable error=%s", type(exc).__name__)
                    # Invalid or partially generated optional material is not published.
                    strategic_result = None
                    ideation_result = None
                    status = ResearchReportStatus.CONTENT_UNAVAILABLE
            return validate_research_report(ResearchReport(
                status, run, pack, interpretation_result, strategic_result, ideation_result
            ))

        if self._interpretation is None or self._strategy is None or self._ideation is None:
            raise ResearchAIProviderNotConfiguredError("legacy report provider is unavailable")
        # Legacy three-stage pipeline shares one AI-phase budget too.
        deadline = self._ai_deadline()
        interpretation_result = self._run_ai_stage(
            "interpretation",
            lambda: call_with_deadline(self._interpretation.interpret, pack, deadline),
            deadline,
        )
        strategic_context = StrategicContext(
            evidence_pack=pack,
            interpretation_result=interpretation_result,
        )
        strategic_result = self._run_ai_stage(
            "strategy",
            lambda: call_with_deadline(self._strategy.generate, strategic_context, deadline),
            deadline,
        )
        ideation_context = IdeationContext(
            strategic_context=strategic_context,
            strategic_result=strategic_result,
        )
        ideation_result = self._run_ai_stage(
            "ideation",
            lambda: call_with_deadline(self._ideation.generate, ideation_context, deadline),
            deadline,
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
    serp_gateway=None,
    transport: httpx.AsyncBaseTransport | None = None,
    config: AIProviderConfig | None,
) -> ResearchReportService:
    """Wire the report service from our clients.

    ``transport`` is an optional async transport injected by tests; production
    passes ``None`` and each request builds a fresh ``AsyncClient``.
    """
    research = build_research_application_service(
        youtube_client=youtube_client,
        facebook_client=facebook_client,
        serp_gateway=serp_gateway,
    )
    if config is None:
        return ResearchReportService(research)
    interpretation = GroundedInterpretationService(
        OpenAICompatibleInterpretationProvider(config, transport=transport)
    )
    strategy = GroundedStrategyService(
        OpenAICompatibleStrategyProvider(config, transport=transport)
    )
    ideation = GroundedIdeationService(
        OpenAICompatibleIdeationProvider(config, transport=transport)
    )
    # The configured AI timeout becomes the shared total AI-phase budget:
    # interpretation + its retry + optional strategy/ideation together must
    # finish within it; the in-flight request is cancelled at expiry.
    return ResearchReportService(
        research,
        interpretation,
        strategy,
        ideation,
        ai_phase_budget_seconds=config.timeout_seconds,
    )
