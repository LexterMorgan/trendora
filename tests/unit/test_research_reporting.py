"""M23A research report orchestration + validation tests. Fully mocked."""

from __future__ import annotations

from datetime import date, datetime, timezone

import httpx
import pytest

from trendora.connectors.youtube.client import YouTubeClient
from trendora.research import (
    AIInterpretation,
    ContentBrief,
    ContentGap,
    ContentIdea,
    EvidenceFact,
    EvidenceField,
    EvidencePack,
    IdeationContext,
    IdeationResult,
    InterpretationResult,
    MarketBasis,
    ModelProvenance,
    Opportunity,
    PatternCitation,
    ReferenceAnalysis,
    ResearchAIProviderError,
    ResearchAIResponseError,
    ResearchApplicationService,
    ResearchCapabilityResolver,
    ResearchInterpretationError,
    ResearchMetrics,
    ResearchNoCoverageError,
    ResearchQuery,
    ResearchReference,
    ResearchReport,
    ResearchReportService,
    ResearchReportStatus,
    ResearchRun,
    ResearchRunStatus,
    StrategicContext,
    StrategicResult,
    YouTubeResearchRetriever,
    aggregate_patterns,
    analyze_references,
    validate_research_report,
)
from trendora.research.reporting import (
    GroundedIdeationService,
    GroundedInterpretationService,
    GroundedStrategyService,
)
from tests.fixtures.youtube_responses import SEARCH_EMPTY, SEARCH_PAGE_1, VIDEOS_LIST_OK

UTC = timezone.utc


def _reference(external: str, *, title: str) -> ResearchReference:
    return ResearchReference(
        source_code="youtube",
        content_external_id=external,
        collected_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        url=f"https://www.youtube.com/watch?v={external}",
        title=title,
        description="guide: https://example.com",
        published_at=datetime(2026, 8, 1, 8, 0, tzinfo=UTC),
        channel_external_id="UCx",
        channel_title="Example Channel",
        market_context="SG",
        market_basis=MarketBasis.YOUTUBE_REGION_AVAILABILITY,
        source_rank=1,
        metrics=ResearchMetrics(view_count=100, like_count=None, comment_count=5),
    )


def _query() -> dict:
    return dict(
        topic="AI education",
        market="SG",
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 31),
        sources=["youtube"],
        result_limit=20,
    )


def _pattern_type(pack: EvidencePack):
    return pack.patterns[0].observation_type


def _grounded_interpretation(pack: EvidencePack) -> InterpretationResult:
    return InterpretationResult(
        model_provenance=ModelProvenance(provider="test", model="test-model"),
        interpretations=(
            AIInterpretation("mix of numbered framing", (PatternCitation(_pattern_type(pack)),)),
        ),
    )


def _grounded_strategy(context: StrategicContext) -> StrategicResult:
    obs = _pattern_type(context.evidence_pack)
    return StrategicResult(
        model_provenance=ModelProvenance(provider="test", model="test-model"),
        content_gaps=(ContentGap("Limited beginner guidance.", (PatternCitation(obs),), (0,)),),
        opportunities=(Opportunity("Explore beginner workflow education.", (0,), (PatternCitation(obs),)),),
    )


def _grounded_ideation(context) -> IdeationResult:
    obs = _pattern_type(context.strategic_context.evidence_pack)
    return IdeationResult(
        model_provenance=ModelProvenance(provider="test", model="test-model"),
        content_ideas=(ContentIdea("5 AI Tools for Beginners", "workflow", (0,), (PatternCitation(obs),)),),
        content_briefs=(
            ContentBrief(0, "educate", "video", "numeral hook", ("intro", "list"), (PatternCitation(obs),)),
        ),
    )


class RecordingInterpretationProvider:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.last_pack = None

    def interpret(self, pack: EvidencePack) -> InterpretationResult:
        self.events.append("interpretation")
        self.last_pack = pack
        return _grounded_interpretation(pack)


class RecordingStrategyProvider:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.last_context = None

    def generate(self, context: StrategicContext) -> StrategicResult:
        self.events.append("strategy")
        self.last_context = context
        return _grounded_strategy(context)


class RecordingIdeationProvider:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.last_context = None

    def generate(self, context) -> IdeationResult:
        self.events.append("ideation")
        self.last_context = context
        return _grounded_ideation(context)


def _youtube_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/search"):
        return httpx.Response(200, json=SEARCH_PAGE_1)
    return httpx.Response(200, json=VIDEOS_LIST_OK)


def _research(handler) -> ResearchApplicationService:
    client = YouTubeClient("test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    retriever = YouTubeResearchRetriever(client)
    return ResearchApplicationService(ResearchCapabilityResolver(), {"youtube": retriever})


def _report_service(events: list[str], *, handler=_youtube_handler) -> ResearchReportService:
    interpretation = GroundedInterpretationService(RecordingInterpretationProvider(events))
    strategy = GroundedStrategyService(RecordingStrategyProvider(events))
    ideation = GroundedIdeationService(RecordingIdeationProvider(events))
    return ResearchReportService(_research(handler), interpretation, strategy, ideation)


class TestOrchestration:
    def test_full_pipeline_order_and_single_execution(self) -> None:
        events: list[str] = []
        report = _report_service(events).build_report(**_query())
        assert report.status is ResearchReportStatus.COMPLETED
        assert report.research_run.status is ResearchRunStatus.COMPLETED
        assert events == ["interpretation", "strategy", "ideation"]
        assert report.evidence_pack is not None
        assert report.interpretation_result is not None
        assert report.strategic_result is not None
        assert report.ideation_result is not None

    def test_same_objects_flow_between_stages(self) -> None:
        events: list[str] = []
        interp = RecordingInterpretationProvider(events)
        strategy = RecordingStrategyProvider(events)
        ideation = RecordingIdeationProvider(events)
        service = ResearchReportService(
            _research(_youtube_handler),
            GroundedInterpretationService(interp),
            GroundedStrategyService(strategy),
            GroundedIdeationService(ideation),
        )
        report = service.build_report(**_query())
        assert strategy.last_context.evidence_pack is interp.last_pack
        assert strategy.last_context.evidence_pack is report.evidence_pack
        assert ideation.last_context.strategic_result is report.strategic_result

    def test_blocked_run_stops_before_ai(self) -> None:
        events: list[str] = []
        service = _report_service(events)
        query = _query()
        query["sources"] = ["instagram", "tiktok"]
        with pytest.raises(ResearchNoCoverageError):
            service.build_report(**query)
        assert events == []

    def test_zero_references_returns_no_evidence_without_ai(self) -> None:
        events: list[str] = []

        def empty_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=SEARCH_EMPTY)

        report = _report_service(events, handler=empty_handler).build_report(**_query())
        assert report.status is ResearchReportStatus.NO_EVIDENCE
        assert report.research_run.references == ()
        assert report.evidence_pack is None
        assert report.interpretation_result is None
        assert report.strategic_result is None
        assert report.ideation_result is None
        assert events == []

    def test_empty_ai_stage_results_remain_executed_non_null(self) -> None:
        class EmptyInterp:
            def interpret(self, pack):
                return InterpretationResult(
                    model_provenance=ModelProvenance(provider="test", model="m"),
                    interpretations=(),
                )

        class EmptyStrategy:
            def generate(self, context):
                return StrategicResult(
                    model_provenance=ModelProvenance(provider="test", model="m"),
                    content_gaps=(),
                    opportunities=(),
                )

        class EmptyIdeation:
            def generate(self, context):
                return IdeationResult(
                    model_provenance=ModelProvenance(provider="test", model="m"),
                    content_ideas=(),
                    content_briefs=(),
                )

        service = ResearchReportService(
            _research(_youtube_handler),
            GroundedInterpretationService(EmptyInterp()),
            GroundedStrategyService(EmptyStrategy()),
            GroundedIdeationService(EmptyIdeation()),
        )
        report = service.build_report(**_query())
        assert report.status is ResearchReportStatus.COMPLETED
        assert report.interpretation_result.interpretations == ()
        assert report.strategic_result.content_gaps == ()
        assert report.ideation_result.content_ideas == ()

    @pytest.mark.parametrize(
        "error",
        [ResearchAIProviderError("x"), ResearchAIResponseError("x"), ResearchInterpretationError("x")],
    )
    def test_ai_failures_not_converted_to_empty_report(self, error: Exception) -> None:
        class FailingInterp:
            def interpret(self, pack):
                raise error

        service = ResearchReportService(
            _research(_youtube_handler),
            GroundedInterpretationService(FailingInterp()),
            GroundedStrategyService(RecordingStrategyProvider([])),
            GroundedIdeationService(RecordingIdeationProvider([])),
        )
        with pytest.raises(type(error)):
            service.build_report(**_query())


class TestValidation:
    def _completed_run(self, references) -> ResearchRun:
        run = ResearchRun(
            ResearchQuery(topic="t", market="SG", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31))
        )
        run._references = tuple(references)
        run._executed_sources = ("youtube",)
        run._status = ResearchRunStatus.COMPLETED
        return run

    def _completed_report(self) -> ResearchReport:
        references = (_reference("a", title="5 Tools"), _reference("b", title="No Numeral"))
        run = self._completed_run(references)
        analyses = analyze_references(references)
        pack = EvidencePack(analyses=analyses, patterns=aggregate_patterns(analyses))
        interpretation = _grounded_interpretation(pack)
        strategic_context = StrategicContext(pack, interpretation)
        strategic = _grounded_strategy(strategic_context)
        ideation = _grounded_ideation(IdeationContext(strategic_context, strategic))
        return ResearchReport(
            status=ResearchReportStatus.COMPLETED,
            research_run=run,
            evidence_pack=pack,
            interpretation_result=interpretation,
            strategic_result=strategic,
            ideation_result=ideation,
        )

    def test_valid_completed_report(self) -> None:
        report = self._completed_report()
        assert validate_research_report(report) is report

    def test_no_evidence_valid_and_with_stage_rejected(self) -> None:
        run = self._completed_run(())
        valid = ResearchReport(
            status=ResearchReportStatus.NO_EVIDENCE,
            research_run=run,
            evidence_pack=None,
            interpretation_result=None,
            strategic_result=None,
            ideation_result=None,
        )
        assert validate_research_report(valid) is valid

        bad = ResearchReport(
            status=ResearchReportStatus.NO_EVIDENCE,
            research_run=run,
            evidence_pack=self._completed_report().evidence_pack,
            interpretation_result=None,
            strategic_result=None,
            ideation_result=None,
        )
        with pytest.raises(ResearchInterpretationError):
            validate_research_report(bad)

    def test_nonterminal_run_rejected(self) -> None:
        run = ResearchRun(
            ResearchQuery(topic="t", market="SG", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31))
        )
        report = ResearchReport(
            status=ResearchReportStatus.NO_EVIDENCE,
            research_run=run,
            evidence_pack=None,
            interpretation_result=None,
            strategic_result=None,
            ideation_result=None,
        )
        with pytest.raises(ResearchInterpretationError):
            validate_research_report(report)

    def test_completed_with_empty_references_rejected(self) -> None:
        report = self._completed_report()
        bad = ResearchReport(
            status=ResearchReportStatus.COMPLETED,
            research_run=self._completed_run(()),
            evidence_pack=report.evidence_pack,
            interpretation_result=report.interpretation_result,
            strategic_result=report.strategic_result,
            ideation_result=report.ideation_result,
        )
        with pytest.raises(ResearchInterpretationError):
            validate_research_report(bad)

    def test_missing_stage_rejected(self) -> None:
        report = self._completed_report()
        bad = ResearchReport(
            status=ResearchReportStatus.COMPLETED,
            research_run=report.research_run,
            evidence_pack=report.evidence_pack,
            interpretation_result=None,
            strategic_result=report.strategic_result,
            ideation_result=report.ideation_result,
        )
        with pytest.raises(ResearchInterpretationError):
            validate_research_report(bad)

    def test_blank_url_rejected(self) -> None:
        reference = _reference("a", title="5 Tools")
        reference = ResearchReference(
            source_code=reference.source_code,
            content_external_id=reference.content_external_id,
            collected_at=reference.collected_at,
            url=None,
            title=reference.title,
            description=reference.description,
            published_at=reference.published_at,
            channel_external_id=reference.channel_external_id,
            channel_title=reference.channel_title,
            market_context=reference.market_context,
            market_basis=reference.market_basis,
            source_rank=reference.source_rank,
            metrics=reference.metrics,
        )
        analyses = analyze_references((reference,))
        pack = EvidencePack(analyses=analyses, patterns=())
        base = self._completed_report()
        report = ResearchReport(
            status=ResearchReportStatus.COMPLETED,
            research_run=self._completed_run((reference,)),
            evidence_pack=pack,
            interpretation_result=base.interpretation_result,
            strategic_result=base.strategic_result,
            ideation_result=base.ideation_result,
        )
        with pytest.raises(ResearchInterpretationError, match="nonblank original URL"):
            validate_research_report(report)

    def test_reference_identity_mismatch_rejected(self) -> None:
        report = self._completed_report()
        wrong = analyze_references((_reference("zzz", title="Wrong"),))[0]
        bad_pack = EvidencePack(analyses=(wrong,))
        bad = ResearchReport(
            status=ResearchReportStatus.COMPLETED,
            research_run=report.research_run,
            evidence_pack=bad_pack,
            interpretation_result=report.interpretation_result,
            strategic_result=report.strategic_result,
            ideation_result=report.ideation_result,
        )
        with pytest.raises(ResearchInterpretationError, match="must exactly match"):
            validate_research_report(bad)

    def test_reordered_references_rejected(self) -> None:
        report = self._completed_report()
        run = self._completed_run(list(reversed(report.research_run.references)))
        bad = ResearchReport(
            status=ResearchReportStatus.COMPLETED,
            research_run=run,
            evidence_pack=report.evidence_pack,
            interpretation_result=report.interpretation_result,
            strategic_result=report.strategic_result,
            ideation_result=report.ideation_result,
        )
        with pytest.raises(ResearchInterpretationError):
            validate_research_report(bad)

    def test_url_fact_mismatch_rejected(self) -> None:
        report = self._completed_report()
        analysis = report.evidence_pack.analyses[0]
        rebuilt = tuple(
            EvidenceFact(
                reference=analysis.reference,
                field=EvidenceField.URL,
                value="https://wrong.example/watch?v=zzz",
            )
            if fact.field is EvidenceField.URL
            else fact
            for fact in analysis.facts
        )
        tampered = ReferenceAnalysis(
            reference=analysis.reference,
            analysis_basis=analysis.analysis_basis,
            facts=rebuilt,
            observations=analysis.observations,
        )
        bad_pack = EvidencePack(analyses=(tampered, *report.evidence_pack.analyses[1:]))
        bad = ResearchReport(
            status=ResearchReportStatus.COMPLETED,
            research_run=report.research_run,
            evidence_pack=bad_pack,
            interpretation_result=report.interpretation_result,
            strategic_result=report.strategic_result,
            ideation_result=report.ideation_result,
        )
        with pytest.raises(ResearchInterpretationError, match="URL fact"):
            validate_research_report(bad)

    def test_full_chain_to_reference_url(self) -> None:
        report = self._completed_report()
        validate_research_report(report)
        idea = report.ideation_result.content_ideas[0]
        brief = report.ideation_result.content_briefs[0]
        assert brief.idea_index == 0
        assert idea.opportunity_indexes == (0,)
        opportunity = report.strategic_result.opportunities[idea.opportunity_indexes[0]]
        gap = report.strategic_result.content_gaps[opportunity.gap_indexes[0]]
        interpretation = report.interpretation_result.interpretations[gap.supporting_interpretation_indexes[0]]
        assert interpretation.citations
        assert report.research_run.references[0].url == "https://www.youtube.com/watch?v=a"
