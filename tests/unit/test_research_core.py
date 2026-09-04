"""Research Core (M13) tests. No database, no network, no retrieval."""

from __future__ import annotations

from datetime import date

import pytest

from trendora.reference import SOURCE_IDS
from trendora.research import (
    KNOWN_SOURCE_CODES,
    MAX_RESULT_LIMIT,
    CoverageCompleteness,
    CoverageReason,
    CoverageStatus,
    PlatformCapability,
    ResearchCapabilityResolver,
    ResearchQuery,
    ResearchRun,
    ResearchRunStatus,
    ResearchStateError,
    ResearchValidationError,
    SourceCapabilities,
    default_declarations,
    required_capabilities,
    validate_research_query,
)

D1 = date(2026, 8, 1)
D2 = date(2026, 8, 30)


def _query(**kwargs) -> ResearchQuery:
    payload = dict(
        topic="AI education",
        market="SG",
        date_from=D1,
        date_to=D2,
    )
    payload.update(kwargs)
    return ResearchQuery(**payload)


class TestResearchQuery:
    def test_valid_query(self) -> None:
        query = _query()
        assert query.topic == "AI education"
        assert query.market == "SG"
        assert query.source_codes == ("youtube",)
        assert query.result_limit == 50

    def test_blank_topic_rejected(self) -> None:
        with pytest.raises(ResearchValidationError):
            _query(topic="   ")

    def test_invalid_date_range_rejected(self) -> None:
        with pytest.raises(ResearchValidationError):
            _query(date_from=D2, date_to=D1)

    def test_single_day_window_is_valid(self) -> None:
        query = _query(date_from=D1, date_to=D1)
        validate_research_query(query)

    def test_result_limit_must_be_positive_and_bounded(self) -> None:
        with pytest.raises(ResearchValidationError):
            _query(result_limit=0)
        with pytest.raises(ResearchValidationError):
            _query(result_limit=-1)
        with pytest.raises(ResearchValidationError):
            _query(result_limit=MAX_RESULT_LIMIT + 1)
        query = _query(result_limit=MAX_RESULT_LIMIT)
        validate_research_query(query)

    def test_duplicate_sources_deduplicated(self) -> None:
        query = _query(source_codes=("youtube", "YOUTUBE", "youtube "))
        assert query.source_codes == ("youtube",)

    def test_market_normalized_to_upper(self) -> None:
        assert _query(market="sg").market == "SG"

    def test_unsupported_market_rejected(self) -> None:
        with pytest.raises(ResearchValidationError):
            _query(market="US")

    def test_blank_source_rejected(self) -> None:
        with pytest.raises(ResearchValidationError):
            _query(source_codes=("youtube", "  "))

    def test_explicit_empty_sources_rejected(self) -> None:
        with pytest.raises(ResearchValidationError):
            _query(source_codes=())


class TestCapabilities:
    def test_supported_capability_recognized(self) -> None:
        declaration = default_declarations()["youtube"]
        assert PlatformCapability.PUBLIC_SEARCH in declaration.supported

    def test_unsupported_capability_not_declared(self) -> None:
        declaration = default_declarations()["youtube"]
        assert PlatformCapability.HASHTAG_DISCOVERY not in declaration.supported
        assert PlatformCapability.MEDIA_ANALYSIS_AVAILABLE not in declaration.supported

    def test_declarations_are_immutable_sets(self) -> None:
        declaration = default_declarations()["youtube"]
        with pytest.raises(AttributeError):
            declaration.supported.add(PlatformCapability.HASHTAG_DISCOVERY)

    def test_no_capability_in_both_supported_and_conditional(self) -> None:
        with pytest.raises(ValueError):
            SourceCapabilities(
                source_code="x",
                supported=frozenset({PlatformCapability.PUBLIC_SEARCH}),
                conditional=frozenset({PlatformCapability.PUBLIC_SEARCH}),
            )

    def test_known_sources_match_canonical_registry(self) -> None:
        assert "youtube" in KNOWN_SOURCE_CODES
        assert "github" in KNOWN_SOURCE_CODES


class TestCoverageResolution:
    def test_available_source(self) -> None:
        result = ResearchCapabilityResolver().resolve(_query(source_codes=("youtube",)))
        item = result.sources[0]
        assert item.source_code == "youtube"
        assert item.status is CoverageStatus.AVAILABLE
        assert item.reason is None

    def test_unsupported_capability_on_known_source(self) -> None:
        # hacker_news does not declare public_search.
        result = ResearchCapabilityResolver().resolve(_query(source_codes=("hacker_news",)))
        item = result.sources[0]
        assert item.status is CoverageStatus.UNAVAILABLE
        assert item.reason is CoverageReason.CAPABILITY_NOT_SUPPORTED

    def test_unknown_source(self) -> None:
        result = ResearchCapabilityResolver().resolve(_query(source_codes=("instagram",)))
        item = result.sources[0]
        assert item.status is CoverageStatus.UNAVAILABLE
        assert item.reason is CoverageReason.SOURCE_UNKNOWN

    def test_known_source_without_declaration(self) -> None:
        result = ResearchCapabilityResolver().resolve(_query(source_codes=("wikimedia",)))
        item = result.sources[0]
        assert item.status is CoverageStatus.UNAVAILABLE
        assert item.reason is CoverageReason.CAPABILITY_NOT_SUPPORTED

    def test_multiple_requested_sources(self) -> None:
        result = ResearchCapabilityResolver().resolve(
            _query(source_codes=("youtube", "hacker_news", "instagram"))
        )
        assert [item.source_code for item in result.sources] == [
            "youtube",
            "hacker_news",
            "instagram",
        ]
        assert result.sources[0].status is CoverageStatus.AVAILABLE
        assert result.sources[1].status is CoverageStatus.UNAVAILABLE
        assert result.sources[2].status is CoverageStatus.UNAVAILABLE

    def test_deterministic_ordering_follows_query(self) -> None:
        resolver = ResearchCapabilityResolver()
        first = resolver.resolve(_query(source_codes=("github", "youtube")))
        second = resolver.resolve(_query(source_codes=("github", "youtube")))
        assert [(s.source_code, s.status) for s in first.sources] == [
            (s.source_code, s.status) for s in second.sources
        ]

    def test_conditional_capability_reports_authorization_required(self) -> None:
        declaration = SourceCapabilities(
            source_code="wikimedia",
            supported=frozenset(),
            conditional=frozenset({PlatformCapability.PUBLIC_SEARCH}),
        )
        resolver = ResearchCapabilityResolver(declarations={"wikimedia": declaration})
        result = resolver.resolve(_query(source_codes=("wikimedia",)))
        item = result.sources[0]
        assert item.status is CoverageStatus.CONDITIONAL
        assert item.reason is CoverageReason.AUTHORIZATION_REQUIRED

    def test_required_capability_is_public_search(self) -> None:
        assert required_capabilities(_query()) == (PlatformCapability.PUBLIC_SEARCH,)


class TestCompleteness:
    def test_complete_coverage(self) -> None:
        result = ResearchCapabilityResolver().resolve(_query(source_codes=("youtube",)))
        assert result.completeness is CoverageCompleteness.COMPLETE

    def test_partial_coverage(self) -> None:
        result = ResearchCapabilityResolver().resolve(
            _query(source_codes=("youtube", "instagram", "tiktok"))
        )
        assert result.completeness is CoverageCompleteness.PARTIAL

    def test_none_coverage(self) -> None:
        result = ResearchCapabilityResolver().resolve(
            _query(source_codes=("instagram", "tiktok"))
        )
        assert result.completeness is CoverageCompleteness.NONE


class TestResearchRun:
    def test_initial_state(self) -> None:
        run = ResearchRun(_query())
        assert run.status is ResearchRunStatus.REQUESTED
        assert run.coverage is None

    def test_youtube_only_resolves_ready_and_complete(self) -> None:
        run = ResearchRun(_query(source_codes=("youtube",)))
        run.resolve_capabilities(ResearchCapabilityResolver())
        assert run.status is ResearchRunStatus.READY
        assert run.coverage is not None
        assert run.coverage.completeness is CoverageCompleteness.COMPLETE

    def test_partial_coverage_resolves_ready(self) -> None:
        run = ResearchRun(_query(source_codes=("youtube", "instagram")))
        run.resolve_capabilities(ResearchCapabilityResolver())
        assert run.status is ResearchRunStatus.READY
        assert run.coverage.completeness is CoverageCompleteness.PARTIAL

    def test_all_unavailable_resolves_blocked(self) -> None:
        run = ResearchRun(_query(source_codes=("instagram", "tiktok")))
        run.resolve_capabilities(ResearchCapabilityResolver())
        assert run.status is ResearchRunStatus.BLOCKED
        assert run.coverage.completeness is CoverageCompleteness.NONE

    def test_ready_is_not_a_completion_state(self) -> None:
        # Capability resolution success is not research execution completion.
        run = ResearchRun(_query(source_codes=("youtube",)))
        run.resolve_capabilities(ResearchCapabilityResolver())
        assert run.status is ResearchRunStatus.READY
        # M14 extends READY into execution states; READY alone never means done.
        assert {s.value for s in ResearchRunStatus} == {
            "requested",
            "resolving_capabilities",
            "ready",
            "blocked",
            "collecting",
            "normalizing",
            "completed",
            "failed",
        }

    def test_invalid_transition_rejected(self) -> None:
        run = ResearchRun(_query())
        run.resolve_capabilities(ResearchCapabilityResolver())
        assert run.status is ResearchRunStatus.READY
        with pytest.raises(ResearchStateError):
            run.resolve_capabilities(ResearchCapabilityResolver())

    def test_source_unavailable_does_not_block_whole_run(self) -> None:
        run = ResearchRun(_query(source_codes=("youtube", "tiktok")))
        run.resolve_capabilities(ResearchCapabilityResolver())
        assert run.status is ResearchRunStatus.READY
        assert run.coverage.sources[0].status is CoverageStatus.AVAILABLE


class TestInvariants:
    """Negative guarantees the M13 core must hold."""

    def test_facebook_known_but_not_persisted(self) -> None:
        assert "facebook" in KNOWN_SOURCE_CODES
        assert "facebook" not in SOURCE_IDS

    def test_source_cannot_claim_capability_absent_from_declaration(self) -> None:
        resolver = ResearchCapabilityResolver()
        declarations = resolver.declarations
        for source_code in KNOWN_SOURCE_CODES:
            query = _query(
                source_codes=(source_code,),
                facebook_page_id="page1" if source_code == "facebook" else None,
            )
            result = resolver.resolve(query)
            for item in result.sources:
                declaration = declarations.get(source_code)
                if item.status is CoverageStatus.AVAILABLE:
                    assert declaration is not None
                    assert item.capability in declaration.supported

    def test_resolver_cannot_substitute_another_capability(self) -> None:
        resolver = ResearchCapabilityResolver()
        result = resolver.resolve(_query(source_codes=("hacker_news",)))
        item = result.sources[0]
        assert item.capability is PlatformCapability.PUBLIC_SEARCH
        assert item.status is CoverageStatus.UNAVAILABLE

    def test_unknown_source_cannot_become_available(self) -> None:
        resolver = ResearchCapabilityResolver()
        for source_code in ("instagram", "tiktok", "nonexistent"):
            result = resolver.resolve(_query(source_codes=(source_code,)))
            item = result.sources[0]
            assert item.status is CoverageStatus.UNAVAILABLE
            assert item.reason is CoverageReason.SOURCE_UNKNOWN

    def test_every_available_result_is_backed_by_declaration(self) -> None:
        resolver = ResearchCapabilityResolver()
        declarations = resolver.declarations
        for source_code in ("youtube", "hacker_news", "stack_exchange", "github"):
            result = resolver.resolve(_query(source_codes=(source_code,)))
            item = result.sources[0]
            if item.status is CoverageStatus.AVAILABLE:
                assert source_code in declarations
                assert item.capability in declarations[source_code].supported

    def test_partial_coverage_is_not_mislabeled_complete(self) -> None:
        result = ResearchCapabilityResolver().resolve(
            _query(source_codes=("youtube", "instagram"))
        )
        assert result.completeness is CoverageCompleteness.PARTIAL
        assert not all(s.status is CoverageStatus.AVAILABLE for s in result.sources)

    def test_resolution_cannot_claim_content_was_retrieved(self) -> None:
        run = ResearchRun(_query())
        run.resolve_capabilities(ResearchCapabilityResolver())
        assert run.status is ResearchRunStatus.READY
        assert run.coverage.sources[0].status is CoverageStatus.AVAILABLE
        # Coverage resolution is capability truth only; there is no collection
        # artifact on the run and no evidence/reference list.
        assert not hasattr(run.coverage, "content_items")
        assert not hasattr(run.coverage, "references")
