"""M26B combined YouTube + Facebook execution tests. Fully mocked."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from trendora.research import (
    ResearchApplicationService,
    ResearchCapabilityResolver,
    ResearchMetrics,
    ResearchReference,
    ResearchRunStatus,
    ResearchSourceNotConfiguredError,
    ResearchValidationError,
    build_research_application_service,
)
from trendora.research.models import (
    CoverageStatus,
    PlatformCapability,
    allocate_result_limits,
)
from trendora.research.retrieval import ResearchRetriever

UTC = timezone.utc
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _query(**overrides) -> dict:
    base = dict(
        topic="AI education",
        market="SG",
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 31),
        sources=["youtube", "facebook"],
        result_limit=4,
        facebook_page_id="page1",
    )
    base.update(overrides)
    return base


def _reference(source_code: str, external: str, rank: int, **metric_kwargs) -> ResearchReference:
    return ResearchReference(
        source_code=source_code,
        content_external_id=external,
        collected_at=T0,
        url=f"https://example.com/{source_code}/{external}",
        title=f"{source_code} {external}",
        description="desc",
        published_at=T0,
        channel_external_id=None,
        channel_title=None,
        market_context=None,
        market_basis=None,
        source_rank=rank,
        metrics=ResearchMetrics(**metric_kwargs),
    )


class RecordingRetriever:
    """Fake retriever: records the exact query it received; returns fixed refs."""

    def __init__(self, refs: tuple[ResearchReference, ...], error: Exception | None = None):
        self.refs = refs
        self.error = error
        self.calls: list[object] = []

    def collect(self, query, *, collected_at=None):
        self.calls.append(query)
        if self.error is not None:
            raise self.error
        return object()

    def normalize(self, collected):
        return self.refs


def _service(youtube_retriever, facebook_retriever) -> ResearchApplicationService:
    retrievers = {}
    if youtube_retriever is not None:
        retrievers["youtube"] = youtube_retriever
    if facebook_retriever is not None:
        retrievers["facebook"] = facebook_retriever
    return ResearchApplicationService(ResearchCapabilityResolver(), retrievers)


class TestQueryValidation:
    def test_mixed_sources_valid_in_any_order(self) -> None:
        from trendora.research import ResearchQuery

        for codes in (("youtube", "facebook"), ("facebook", "youtube")):
            q = ResearchQuery(
                topic="t", market="SG", date_from=date(2026, 8, 1),
                date_to=date(2026, 8, 31), source_codes=codes,
                result_limit=4, facebook_page_id="page1",
            )
            assert q.source_codes == codes
            assert q.facebook_page_id == "page1"

    def test_mixed_sources_require_page_id(self) -> None:
        from trendora.research import ResearchQuery

        with pytest.raises(ResearchValidationError, match="facebook_page_id"):
            ResearchQuery(
                topic="t", market="SG", date_from=date(2026, 8, 1),
                date_to=date(2026, 8, 31), source_codes=["youtube", "facebook"],
                result_limit=4, facebook_page_id=None,
            )

    def test_page_id_without_facebook_rejected(self) -> None:
        from trendora.research import ResearchQuery

        with pytest.raises(ResearchValidationError):
            ResearchQuery(
                topic="t", market="SG", date_from=date(2026, 8, 1),
                date_to=date(2026, 8, 31), source_codes=["youtube"],
                result_limit=4, facebook_page_id="page1",
            )

    def test_duplicates_deduplicated_preserving_order(self) -> None:
        from trendora.research import ResearchQuery

        q = ResearchQuery(
            topic="t", market="SG", date_from=date(2026, 8, 1),
            date_to=date(2026, 8, 31), source_codes=["youtube", "Facebook", "youtube"],
            result_limit=4, facebook_page_id="page1",
        )
        assert q.source_codes == ("youtube", "facebook")


class TestAllocation:
    def test_even_split(self) -> None:
        assert allocate_result_limits(4, ("youtube", "facebook")) == (
            ("youtube", 2),
            ("facebook", 2),
        )

    def test_odd_limit_remainder_to_earlier_sources(self) -> None:
        assert allocate_result_limits(5, ("youtube", "facebook")) == (
            ("youtube", 3),
            ("facebook", 2),
        )

    def test_three_sources_remainder_first(self) -> None:
        assert allocate_result_limits(8, ("a", "b", "c")) == (("a", 3), ("b", 3), ("c", 2))

    def test_single_source_gets_full_limit(self) -> None:
        assert allocate_result_limits(7, ("youtube",)) == (("youtube", 7),)

    def test_shares_always_sum_to_limit(self) -> None:
        for limit in range(3, 20):
            shares = allocate_result_limits(limit, ("a", "b", "c"))
            assert sum(value for _, value in shares) == limit

    def test_limit_below_source_count_rejected(self) -> None:
        with pytest.raises(ResearchValidationError, match="executable sources"):
            allocate_result_limits(1, ("youtube", "facebook"))


class TestCapabilityResolution:
    def test_per_source_capability_no_cross_product(self) -> None:
        from trendora.research import ResearchQuery

        resolver = ResearchCapabilityResolver()
        q = ResearchQuery(
            topic="t", market="SG", date_from=date(2026, 8, 1),
            date_to=date(2026, 8, 31), source_codes=["youtube", "facebook"],
            result_limit=4, facebook_page_id="page1",
        )
        coverage = resolver.resolve(q)
        assert [item.source_code for item in coverage.sources] == ["youtube", "facebook"]
        assert coverage.sources[0].capability is PlatformCapability.PUBLIC_SEARCH
        assert coverage.sources[1].capability is PlatformCapability.CREATOR_WATCHLIST
        assert all(item.status is CoverageStatus.AVAILABLE for item in coverage.sources)
        assert coverage.completeness.value == "complete"


class TestCombinedExecution:
    def test_both_retrievers_called_once_with_source_specific_queries(self) -> None:
        yt = RecordingRetriever((_reference("youtube", "v1", 1, view_count=10),))
        fb = RecordingRetriever((_reference("facebook", "p1", 1, reaction_count=5),))
        run = _service(yt, fb).execute(**_query(result_limit=3))

        assert run.status is ResearchRunStatus.COMPLETED
        assert len(yt.calls) == 1
        assert len(fb.calls) == 1
        yt_query = yt.calls[0]
        fb_query = fb.calls[0]
        # divmod(3, 2) = (1, 1): base 1 each, remainder 1 to the first source.
        assert yt_query.source_codes == ("youtube",)
        assert yt_query.result_limit == 2
        assert yt_query.facebook_page_id is None
        assert fb_query.source_codes == ("facebook",)
        assert fb_query.result_limit == 1
        assert fb_query.facebook_page_id == "page1"

    def test_merged_order_ranks_urls_metrics_and_executed_sources(self) -> None:
        yt = RecordingRetriever(
            (
                _reference("youtube", "v1", 1, view_count=10, like_count=2, comment_count=1),
                _reference("youtube", "v2", 2, view_count=20, like_count=4, comment_count=2),
            )
        )
        fb = RecordingRetriever(
            (
                _reference("facebook", "p1", 1, reaction_count=5, comment_count=3, share_count=1),
                _reference("facebook", "p2", 2, reaction_count=6, comment_count=4, share_count=2),
            )
        )
        run = _service(yt, fb).execute(**_query(result_limit=4))

        assert run.status is ResearchRunStatus.COMPLETED
        assert run.executed_sources == ("youtube", "facebook")
        refs = run.references
        assert [r.source_code for r in refs] == ["youtube", "youtube", "facebook", "facebook"]
        assert [r.content_external_id for r in refs] == ["v1", "v2", "p1", "p2"]
        assert [r.source_rank for r in refs] == [1, 2, 1, 2]
        assert refs[0].url == "https://example.com/youtube/v1"
        assert refs[0].metrics.view_count == 10 and refs[0].metrics.reaction_count is None
        assert refs[2].metrics.reaction_count == 5 and refs[2].metrics.view_count is None
        # Global cap respected: merged total never exceeds the original limit.
        assert len(refs) <= 4

    def test_missing_retriever_fails_before_any_call(self) -> None:
        yt = RecordingRetriever(())
        service = _service(yt, None)  # facebook requested but unconfigured
        with pytest.raises(ResearchSourceNotConfiguredError):
            service.execute(**_query())
        assert yt.calls == []  # zero retrieval calls

    def test_second_source_failure_marks_failed_and_records_attempts(self) -> None:
        from trendora.research import ResearchQuery
        from trendora.research.application import _source_query
        from trendora.research.models import ResearchRun

        yt = RecordingRetriever((_reference("youtube", "v1", 1, view_count=1),))
        fb = RecordingRetriever((), error=RuntimeError("facebook boom"))
        query = ResearchQuery(
            topic="t", market="SG", date_from=date(2026, 8, 1),
            date_to=date(2026, 8, 31), source_codes=["youtube", "facebook"],
            result_limit=4, facebook_page_id="page1",
        )
        run = ResearchRun(query)
        run.resolve_capabilities(ResearchCapabilityResolver())
        allocations = allocate_result_limits(4, ("youtube", "facebook"))
        entries = tuple(
            (code, _source_query(query, code, limit), retriever)
            for (code, retriever), (_, limit) in zip(
                (("youtube", yt), ("facebook", fb)), allocations, strict=True
            )
        )
        with pytest.raises(RuntimeError, match="facebook boom"):
            run.execute_sources(entries)
        assert run.status is ResearchRunStatus.FAILED
        # Execution truth: both sources were attempted, in attempt order.
        assert run.executed_sources == ("youtube", "facebook")

    def test_first_source_failure_stops_before_later_sources(self) -> None:
        yt = RecordingRetriever((), error=RuntimeError("youtube boom"))
        fb = RecordingRetriever((_reference("facebook", "p1", 1, reaction_count=1),))
        with pytest.raises(RuntimeError, match="youtube boom"):
            _service(yt, fb).execute(**_query())
        assert len(fb.calls) == 0

    def test_all_sources_empty_completes_with_zero_references(self) -> None:
        run = _service(RecordingRetriever(()), RecordingRetriever(())).execute(**_query())
        assert run.status is ResearchRunStatus.COMPLETED
        assert run.references == ()
        assert run.executed_sources == ("youtube", "facebook")

    def test_mixed_empty_result_completes_with_present_source(self) -> None:
        yt = RecordingRetriever(())
        fb = RecordingRetriever((_reference("facebook", "p1", 1, reaction_count=2),))
        run = _service(yt, fb).execute(**_query())
        assert run.status is ResearchRunStatus.COMPLETED
        assert [r.source_code for r in run.references] == ["facebook"]

    def test_builder_registers_both_retrievers(self) -> None:
        service = build_research_application_service(
            youtube_client=object(), facebook_client=object()
        )
        assert service._retrievers.keys() == {"youtube", "facebook"}  # noqa: SLF001


class TestExecutionLifecycle:
    def _plan(self, result_limit: int, retrievers: dict) -> tuple:
        from trendora.research import ResearchQuery
        from trendora.research.application import _source_query
        from trendora.research.models import ResearchRun

        query = ResearchQuery(
            topic="t", market="SG", date_from=date(2026, 8, 1),
            date_to=date(2026, 8, 31), source_codes=["youtube", "facebook"],
            result_limit=result_limit, facebook_page_id="page1",
        )
        run = ResearchRun(query)
        run.resolve_capabilities(ResearchCapabilityResolver())
        allocations = dict(
            allocate_result_limits(result_limit, ("youtube", "facebook"))
        )
        entries = tuple(
            (code, _source_query(query, code, allocations[code]), retriever)
            for code, retriever in (("youtube", retrievers["youtube"]),
                                    ("facebook", retrievers["facebook"]))
        )
        return run, entries

    def test_empty_plan_rejected_before_state_change(self) -> None:
        from trendora.research import ResearchQuery
        from trendora.research.exceptions import ResearchStateError
        from trendora.research.models import ResearchRun

        query = ResearchQuery(
            topic="t", market="SG", date_from=date(2026, 8, 1),
            date_to=date(2026, 8, 31), source_codes=["youtube"],
            result_limit=4,
        )
        run = ResearchRun(query)
        run.resolve_capabilities(ResearchCapabilityResolver())
        assert run.status is ResearchRunStatus.READY
        with pytest.raises(ResearchStateError, match="at least one source"):
            run.execute_sources(())
        assert run.status is ResearchRunStatus.READY

    def test_collect_runs_while_collecting_normalize_while_normalizing(self) -> None:
        class PhaseRetriever:
            def __init__(self, refs, run, phases):
                self.refs = refs
                self.run = run
                self.phases = phases

            def collect(self, query, *, collected_at=None):
                self.phases.append(("collect", self.run.status))
                return object()

            def normalize(self, collected):
                self.phases.append(("normalize", self.run.status))
                return self.refs

        phases: list[tuple[str, ResearchRunStatus]] = []
        yt = PhaseRetriever((_reference("youtube", "v1", 1),), None, phases)
        fb = PhaseRetriever((_reference("facebook", "p1", 1),), None, phases)
        run, entries = self._plan(4, {"youtube": yt, "facebook": fb})
        yt.run = run
        fb.run = run
        run.execute_sources(entries)
        assert run.status is ResearchRunStatus.COMPLETED
        # All collect calls happen while COLLECTING; all normalize calls
        # happen while NORMALIZING.
        assert [phase for phase, _ in phases] == [
            "collect",
            "collect",
            "normalize",
            "normalize",
        ]
        assert all(status is ResearchRunStatus.COLLECTING for phase, status in phases if phase == "collect")
        assert all(status is ResearchRunStatus.NORMALIZING for phase, status in phases if phase == "normalize")

    def test_overproducing_source_capped_later_source_preserved(self) -> None:
        yt = RecordingRetriever(
            (
                _reference("youtube", "v1", 1, view_count=1),
                _reference("youtube", "v2", 2, view_count=2),
                _reference("youtube", "v3", 3, view_count=3),
            )
        )
        fb = RecordingRetriever(
            (
                _reference("facebook", "p1", 1, reaction_count=1),
                _reference("facebook", "p2", 2, reaction_count=2),
            )
        )
        run, entries = self._plan(4, {"youtube": yt, "facebook": fb})
        run.execute_sources(entries)

        assert run.status is ResearchRunStatus.COMPLETED
        refs = run.references
        # YouTube overproduced (3 refs) but keeps only its allocated 2.
        assert [r.content_external_id for r in refs] == ["v1", "v2", "p1", "p2"]
        assert [r.source_code for r in refs] == ["youtube", "youtube", "facebook", "facebook"]
        assert len(refs) <= 4

    def test_normalization_failure_marks_failed(self) -> None:
        class FailingNormalize:
            def collect(self, query, *, collected_at=None):
                return object()

            def normalize(self, collected):
                raise RuntimeError("normalize boom")

        run, entries = self._plan(
            4, {"youtube": FailingNormalize(), "facebook": RecordingRetriever(())}
        )
        with pytest.raises(RuntimeError, match="normalize boom"):
            run.execute_sources(entries)
        assert run.status is ResearchRunStatus.FAILED


class TestCombinedReportPipeline:
    def _report_events(self, events: list[str]):
        from tests.unit.test_research_reporting import (
            RecordingIdeationProvider,
            RecordingInterpretationProvider,
            RecordingStrategyProvider,
        )
        from trendora.research import (
            GroundedIdeationService,
            GroundedInterpretationService,
            GroundedStrategyService,
        )

        interp = RecordingInterpretationProvider(events)
        strategy = RecordingStrategyProvider(events)
        ideation = RecordingIdeationProvider(events)
        return (
            GroundedInterpretationService(interp),
            GroundedStrategyService(strategy),
            GroundedIdeationService(ideation),
            interp,
            strategy,
            ideation,
        )

    def test_combined_report_runs_retrieval_once_and_ai_once(self) -> None:
        from trendora.research import ResearchReportService

        yt = RecordingRetriever(
            (
                _reference("youtube", "v1", 1, view_count=100, like_count=10, comment_count=2),
                _reference("youtube", "v2", 2, view_count=5),
            )
        )
        fb = RecordingRetriever(
            (_reference("facebook", "p1", 1, reaction_count=5, comment_count=2, share_count=1),)
        )
        research = _service(yt, fb)
        events: list[str] = []
        interp, strategy, ideation, interp_p, strategy_p, ideation_p = self._report_events(events)

        report = ResearchReportService(research, interp, strategy, ideation).build_report(**_query())

        assert report.status.value == "completed"
        assert report.research_run.executed_sources == ("youtube", "facebook")
        # Retrieval ran exactly once per source; AI stages ran exactly once.
        assert len(yt.calls) == 1 and len(fb.calls) == 1
        assert interp_p.calls == 1 and strategy_p.calls == 1 and ideation_p.calls == 1
        assert events == ["interpretation", "strategy", "ideation"]
        # Evidence pack covers references from both sources; citation identity
        # stays (source_code, content_external_id).
        analyzed_sources = {a.reference.source_code for a in report.evidence_pack.analyses}
        assert analyzed_sources == {"youtube", "facebook"}
        reference_ids = {a.reference for a in report.evidence_pack.analyses}
        assert len(reference_ids) == 3
