"""M25C Facebook research execution tests. Fully mocked; no live AI/network."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from trendora.research import (
    AIInterpretation,
    ContentBrief,
    ContentGap,
    ContentIdea,
    EvidenceField,
    FactCitation,
    GroundedIdeationService,
    GroundedInterpretationService,
    GroundedStrategyService,
    IdeationContext,
    IdeationResult,
    InterpretationResult,
    ModelProvenance,
    Opportunity,
    PatternCitation,
    ReferenceId,
    ResearchCapabilityResolver,
    ResearchQuery,
    ResearchReportService,
    ResearchRunStatus,
    ResearchSourceNotConfiguredError,
    ResearchValidationError,
    StrategicContext,
    StrategicResult,
    build_research_application_service,
)

UTC = timezone.utc


def _fb_post(post_id: str, *, message: str | None = "hello fb", reactions: int = 5,
             comments: int = 2, shares: int = 1,
             created: str = "2026-08-10T08:00:00+0000") -> dict:
    item: dict = {
        "id": post_id,
        "from": {"id": "page1", "name": "Page"},
        "created_time": created,
        "permalink_url": f"https://www.facebook.com/p/{post_id}",
    }
    if message is not None:
        item["message"] = message
    item["reactions"] = {"summary": {"total_count": reactions}}
    item["comments"] = {"summary": {"total_count": comments}}
    item["shares"] = {"count": shares}
    return item


class RecordingFacebookClient:
    """Deterministic fake client: records calls; never leaks httpx instances."""

    def __init__(self, posts: list):
        self.posts = posts
        self.calls: list[dict] = []
        self.closed = 0

    def list_page_posts(self, page_id, *, date_from, date_to, limit):
        self.calls.append({
            "page_id": page_id,
            "date_from": date_from,
            "date_to": date_to,
            "limit": limit,
        })
        from trendora.connectors.facebook.schemas import FacebookPostResource

        return tuple(FacebookPostResource.model_validate(item) for item in self.posts)

    def close(self):
        self.closed += 1


def _query(**overrides) -> dict:
    base = dict(
        topic="ignored for facebook",
        market="SG",
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 31),
        sources=["facebook"],
        result_limit=10,
        facebook_page_id="page1",
    )
    base.update(overrides)
    return base


class TestQueryValidation:
    def test_valid_facebook_query_and_normalized_page_id(self) -> None:
        q = ResearchQuery(topic="t", market="SG", date_from=date(2026, 8, 1),
                          date_to=date(2026, 8, 31), source_codes=("facebook",),
                          result_limit=10, facebook_page_id="  page1  ")
        assert q.facebook_page_id == "page1"

    def test_missing_page_id_rejected(self) -> None:
        with pytest.raises(ResearchValidationError, match="facebook_page_id"):
            ResearchQuery(topic="t", market="SG", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31),
                          source_codes=["facebook"], result_limit=10, facebook_page_id=None)

    def test_unsafe_page_id_rejected(self) -> None:
        for bad in ("a/b", "..", "a b", "a..b", "."):
            with pytest.raises(ResearchValidationError):
                ResearchQuery(topic="t", market="SG", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31),
                               source_codes=["facebook"], result_limit=10, facebook_page_id=bad)

    def test_unsafe_page_id_with_youtube_rejected(self) -> None:
        for bad in ("../", "  ", "x/y", ".."):
            with pytest.raises(ResearchValidationError):
                ResearchQuery(topic="t", market="SG", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31),
                               source_codes=["youtube"], result_limit=10, facebook_page_id=bad)

    def test_valid_page_id_with_youtube_rejected(self) -> None:
        with pytest.raises(ResearchValidationError, match="requires exactly sources"):
            ResearchQuery(topic="t", market="SG", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31),
                           source_codes=["youtube"], result_limit=10, facebook_page_id="page1")

    def test_mixed_fb_with_other_source_rejected(self) -> None:
        with pytest.raises(ResearchValidationError):
            ResearchQuery(topic="t", market="SG", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31),
                           source_codes=["facebook", "youtube"], result_limit=10, facebook_page_id="page1")

    def test_default_youtube_query_unchanged(self) -> None:
        q = ResearchQuery(topic="t", market="SG", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31))
        assert q.source_codes == ("youtube",)
        assert q.facebook_page_id is None


class TestCapabilities:
    def test_facebook_resolves_creator_watchlist(self) -> None:
        resolver = ResearchCapabilityResolver()
        q = ResearchQuery(topic="t", market="SG", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31),
                           source_codes=["facebook"], result_limit=10, facebook_page_id="page1")
        item = resolver.resolve(q).sources[0]
        assert item.source_code == "facebook"
        assert item.capability.value == "creator_watchlist"
        assert item.status.value == "available"
        assert item.reason is None


class TestAppService:
    def _service(self, client):
        from trendora.research.facebook import FacebookResearchRetriever
        from trendora.research import ResearchApplicationService

        return ResearchApplicationService(
            ResearchCapabilityResolver(),
            {"facebook": FacebookResearchRetriever(client)},
        )

    def test_facebook_request_passes_exact_args_once(self) -> None:
        posts = [_fb_post("p1"), _fb_post("p2")]
        client = RecordingFacebookClient(posts)
        run = self._service(client).execute(**_query())
        assert run.status is ResearchRunStatus.COMPLETED
        assert run.executed_sources == ("facebook",)
        assert len(client.calls) == 1
        call = client.calls[0]
        assert call["page_id"] == "page1"
        assert call["date_from"] == date(2026, 8, 1)
        assert call["date_to"] == date(2026, 8, 31)
        assert call["limit"] == 10

    def test_references_survive_with_source_order_ranks_metrics(self) -> None:
        client = RecordingFacebookClient([_fb_post("p1"), _fb_post("p2")])
        run = self._service(client).execute(**_query())
        refs = run.references or ()
        assert [r.content_external_id for r in refs] == ["p1", "p2"]
        assert [r.source_rank for r in refs] == [1, 2]
        assert [r.url for r in refs] == ["https://www.facebook.com/p/p1", "https://www.facebook.com/p/p2"]
        assert refs[0].metrics.reaction_count == 5
        assert refs[0].metrics.comment_count == 2
        assert refs[0].metrics.share_count == 1
        assert refs[0].metrics.like_count is None
        collected = refs[0].collected_at
        assert collected.utcoffset() is not None

    def test_injected_client_never_closed_by_service(self) -> None:
        client = RecordingFacebookClient([])
        self._service(client).execute(**_query())
        assert client.closed == 0

    def test_facebook_zero_posts_completes_empty(self) -> None:
        run = self._service(RecordingFacebookClient([])).execute(**_query())
        assert run.status is ResearchRunStatus.COMPLETED
        assert (run.references or ()) == ()

    def test_facebook_without_client_raises_not_configured(self) -> None:
        service = build_research_application_service(
            youtube_client=None, facebook_client=None
        )
        with pytest.raises(ResearchSourceNotConfiguredError):
            service.execute(**_query())


def _recorded_interpretation_service(events: list, pack_fact_citation=False):
    class Rec:
        def __init__(self):
            self.pack = None
        def interpret(self, pack):
            events.append("interpretation")
            self.pack = pack
            citations = []
            if pack_fact_citation:
                ref = pack.analyses[0].reference
                citations.append(FactCitation(reference=ref, field=EvidenceField.REACTION_COUNT))
            citations.append(PatternCitation(pack.patterns[0].observation_type))
            return InterpretationResult(
                model_provenance=ModelProvenance(provider="test", model="m"),
                interpretations=(AIInterpretation("fb evidence reading", tuple(citations)),),
            )
    rec = Rec()
    return GroundedInterpretationService(rec), rec


def _recorded_strategy_service(events):
    class Rec:
        def __init__(self):
            self.context = None
        def generate(self, context):
            events.append("strategy")
            self.context = context
            cite = context.interpretation_result.interpretations[0].citations[0]
            return StrategicResult(
                model_provenance=ModelProvenance(provider="test", model="m"),
                content_gaps=(ContentGap("limited", (cite,), (0,)),),
                opportunities=(Opportunity("opp", (0,), (cite,)),),
            )
    rec = Rec()
    return GroundedStrategyService(rec), rec


def _recorded_ideation_service(events):
    class Rec:
        def __init__(self):
            self.context = None
        def generate(self, context):
            events.append("ideation")
            self.context = context
            cite = context.strategic_result.opportunities[0].citations[0]
            return IdeationResult(
                model_provenance=ModelProvenance(provider="test", model="m"),
                content_ideas=(ContentIdea("Idea", "angle", (0,), (cite,)),),
                content_briefs=(ContentBrief(0, "obj", "fmt", "hook", ("a",), (cite,)),),
            )
    rec = Rec()
    return GroundedIdeationService(rec), rec


def _report_service(client, events, fact_citation=False):
    interp, _ = _recorded_interpretation_service(events, pack_fact_citation=fact_citation)
    strat, _ = _recorded_strategy_service(events)
    ideat, _ = _recorded_ideation_service(events)
    from trendora.research import ResearchApplicationService
    from trendora.research.facebook import FacebookResearchRetriever

    research = ResearchApplicationService(
        ResearchCapabilityResolver(),
        {"facebook": FacebookResearchRetriever(client)},
    )
    return ResearchReportService(research, interp, strat, ideat)


class TestReportService:
    def test_zero_posts_returns_no_evidence_without_ai(self) -> None:
        events: list[str] = []
        service = _report_service(RecordingFacebookClient([]), events)
        report = service.build_report(**_query())
        assert report.status.value == "no_evidence"
        assert (report.research_run.references or ()) == ()
        assert events == []

    def test_nonempty_report_runs_ai_once_each_with_fb_metric_citation(self) -> None:
        events: list[str] = []
        client = RecordingFacebookClient([_fb_post("p1"), _fb_post("p2")])
        service = _report_service(client, events, fact_citation=True)
        report = service.build_report(**_query())
        assert report.status.value == "completed"
        assert report.research_run.executed_sources == ("facebook",)
        assert events == ["interpretation", "strategy", "ideation"]
        # reaction, comment, share facts all present
        facts = report.evidence_pack.analyses[0].facts
        fv = {f.field.value: f.value for f in facts}
        assert fv["reaction_count"] == 5
        assert fv["comment_count"] == 2
        assert fv["share_count"] == 1
        # first FactCitation propagates through every grounded stage
        expected = FactCitation(
            reference=ReferenceId("facebook", "p1"),
            field=EvidenceField.REACTION_COUNT,
        )
        assert report.interpretation_result.interpretations[0].citations[0] == expected
        assert report.strategic_result.content_gaps[0].citations[0] == expected
        assert report.strategic_result.opportunities[0].citations[0] == expected
        assert report.ideation_result.content_ideas[0].citations[0] == expected
        assert report.ideation_result.content_briefs[0].citations[0] == expected
        # full chain passes validation; brief/idea present
        assert report.ideation_result.content_briefs[0].idea_index == 0
        assert report.ideation_result.content_ideas[0].opportunity_indexes == (0,)
        # reference identity is facebook:<id>
        assert report.evidence_pack.analyses[0].reference == ReferenceId("facebook", "p1")
        assert client.closed == 0
