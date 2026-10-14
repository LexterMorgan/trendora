"""Deterministic AI-input compaction for the interpretation stage.

Network is fully mocked. These tests prove contracts and failure behavior; they
cannot prove that a live model writes better prose.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from trendora.api.research_report_models import to_report_response
from trendora.research.ai_execution import GroundedInterpretationService
from trendora.research.ai_input import (
    MAX_DESCRIPTION_CHARS,
    MAX_INPUT_REFERENCES,
    MAX_TITLE_CHARS,
    build_interpretation_input,
    payload_size,
    select_analyses,
    truncate_text,
)
from trendora.research.ai_provider import (
    AIProviderConfig,
    OpenAICompatibleInterpretationProvider,
    evidence_pack_to_payload,
)
from trendora.research.evidence import EvidenceField, ObservationType, analyze_references
from trendora.research.exceptions import ResearchInterpretationError
from trendora.research.interpretation import (
    AIInterpretation,
    PatternCitation,
    EvidencePack,
    FactCitation,
    InterpretationResult,
    ModelProvenance,
    validate_interpretations,
    validate_text_supported_interpretations,
)
from trendora.research.models import (
    MarketBasis,
    ResearchMetrics,
    ResearchQuery,
    ResearchReference,
)
from trendora.research.patterns import aggregate_patterns
from tests.unit.test_research_reporting import _query, _report_service

UTC = timezone.utc


def _youtube_reference(i: int) -> ResearchReference:
    return ResearchReference(
        source_code="youtube", content_external_id=f"v{i}",
        collected_at=datetime(2026, 10, 1, tzinfo=UTC),
        url=f"https://www.youtube.com/watch?v=v{i}",
        title=f"How AI tool {i} transforms classroom teaching in 2026",
        description=("A detailed walkthrough of tool %d and its classroom use. " % i) * 8,
        published_at=datetime(2026, 9, 20, tzinfo=UTC),
        channel_external_id="UCx", channel_title=f"Channel {i}",
        market_context="SG", market_basis=MarketBasis.YOUTUBE_REGION_AVAILABILITY,
        source_rank=i, metrics=ResearchMetrics(view_count=1000 + i, like_count=10, comment_count=2),
    )


def _web_ref(i: int, *, published: bool = False) -> ResearchReference:
    return ResearchReference(
        source_code="public_web", content_external_id=f"https://site{i}.example/story",
        collected_at=datetime(2026, 10, 1, tzinfo=UTC),
        url=f"https://site{i}.example/story",
        title=f"AI education platform {i} launches new feature",
        description=("Coverage of the platform %d announcement. " % i) * 6,
        published_at=datetime(2026, 9, 25, tzinfo=UTC) if published else None,
        channel_title=f"site{i}.example", source_rank=i,
    )


def _dominating_pack() -> EvidencePack:
    refs = tuple([_youtube_reference(i) for i in range(1, 26)] + [_web_ref(i) for i in range(1, 16)])
    analyses = analyze_references(refs)
    query = ResearchQuery(
        topic="AI tools for education", markets=(), date_from=date(2026, 9, 11),
        date_to=date(2026, 10, 10), source_codes=("youtube", "public_web"), result_limit=40,
    )
    return EvidencePack(analyses, aggregate_patterns(analyses), research_query=query)


class TestReduction:
    def test_compaction_removes_redundant_material_and_is_measured(self):
        pack = _dominating_pack()
        compacted = build_interpretation_input(pack)
        before, after = payload_size(pack), payload_size(compacted)
        assert after < before * 0.5, f"expected a large reduction, got {before} -> {after}"

        payload = evidence_pack_to_payload(compacted)
        fields = {fact["field"] for analysis in payload["references"] for fact in analysis["facts"]}
        assert fields == {"title", "description", "published_at", "channel_title"}
        # Redundant representations removed: per-reference shape observations and
        # every engagement/metadata fact.
        assert all(analysis["observations"] == [] for analysis in payload["references"])
        assert {"url", "collected_at", "view_count", "like_count", "comment_count",
                "reaction_count", "share_count", "source_rank", "market_contexts",
                "market_basis"}.isdisjoint(fields)
        # Patterns are omitted entirely: their counts are full-pack facts, and a
        # saved report would resolve the same citation against those full counts.
        assert payload["patterns"] == []
        assert pack.patterns, "the stored pack keeps its pattern aggregates"

    def test_original_pack_is_not_mutated(self):
        pack = _dominating_pack()
        build_interpretation_input(pack)
        assert len(pack.analyses) == 40
        assert all(analysis.observations for analysis in pack.analyses)
        assert any(fact.field is EvidenceField.VIEW_COUNT for fact in pack.analyses[0].facts)

    def test_long_text_is_bounded_at_a_word_boundary(self):
        assert truncate_text("short", 100) == "short"
        bounded = truncate_text("word " * 400, MAX_DESCRIPTION_CHARS)
        assert len(bounded) <= MAX_DESCRIPTION_CHARS + 1 and bounded.endswith("…")
        # Long unbroken text and multi-byte text are still bounded, and the
        # truncation marker makes the partial text explicit.
        unbroken = truncate_text("x" * 5000, MAX_DESCRIPTION_CHARS)
        assert len(unbroken) <= MAX_DESCRIPTION_CHARS + 1 and unbroken.endswith("…")
        unicode_text = truncate_text(("café ☕ naïve " * 200), MAX_DESCRIPTION_CHARS)
        assert len(unicode_text) <= MAX_DESCRIPTION_CHARS + 1 and unicode_text.endswith("…")
        # End to end: an over-long title and description are bounded in the input.
        ref = ResearchReference(
            source_code="youtube", content_external_id="long-video",
            collected_at=datetime(2026, 10, 1, tzinfo=UTC),
            url="https://www.youtube.com/watch?v=long-video",
            title="t" * 400, description="d" * 900, channel_title="Channel",
            source_rank=1,
        )
        payload = evidence_pack_to_payload(build_interpretation_input(EvidencePack(analyze_references((ref,)))))
        facts = {fact["field"]: fact["value"] for fact in payload["references"][0]["facts"]}
        assert len(facts["title"]) <= MAX_TITLE_CHARS + 1 and facts["title"].endswith("…")
        assert len(facts["description"]) <= MAX_DESCRIPTION_CHARS + 1 and facts["description"].endswith("…")


class TestSelection:
    def test_blank_description_records_are_not_collapsed(self):
        # Two unrelated pages sharing a generic title but no description must
        # never collapse into one.
        common = dict(collected_at=datetime(2026, 10, 1, tzinfo=UTC), description=None,
                      published_at=None, source_rank=1)
        refs = tuple(
            ResearchReference(source_code="public_web", content_external_id=f"https://news{i}.example/x",
                              url=f"https://news{i}.example/x", title="News",
                              channel_title=f"news{i}.example", **common)
            for i in (1, 2)
        )
        selected = build_interpretation_input(EvidencePack(analyze_references(refs))).analyses
        assert len(selected) == 2

    def test_exact_syndicated_duplicates_collapse_to_one(self):
        base = dict(collected_at=datetime(2026, 10, 1, tzinfo=UTC), description="Same press release text.",
                    published_at=None, source_rank=1)
        refs = tuple(
            ResearchReference(source_code="public_web", content_external_id=f"https://site{i}.example/story",
                              url=f"https://site{i}.example/story", title="Platform X launches feature",
                              channel_title=f"site{i}.example", **base)
            for i in range(1, 4)
        )
        selected = build_interpretation_input(EvidencePack(analyze_references(refs))).analyses
        assert [a.reference.content_external_id for a in selected] == ["https://site1.example/story"]

    def test_selection_is_diverse_and_no_source_is_crowded_out(self):
        pack = _dominating_pack()
        selected = build_interpretation_input(pack).analyses
        assert len(selected) == MAX_INPUT_REFERENCES
        # Source-fair round-robin: one per source per round until the cap.
        sources = [analysis.reference.source_code for analysis in selected]
        assert sources.count("youtube") == 12 and sources.count("public_web") == 12
        # Within a source, reference order follows the original collected order.
        youtube_order = [a.reference.content_external_id for a in selected if a.reference.source_code == "youtube"]
        original_youtube = [a.reference.content_external_id for a in pack.analyses if a.reference.source_code == "youtube"]
        assert youtube_order == original_youtube[: len(youtube_order)]
        # Within a source, domains are taken in first-seen order.
        domains = [
            next(f.value for f in analysis.facts if f.field is EvidenceField.CHANNEL_TITLE)
            for analysis in selected
            if analysis.reference.source_code == "public_web"
        ]
        assert domains == [f"site{i}.example" for i in range(1, 13)]


class TestCitationIntegrity:
    def test_compact_research_input_has_no_patterns_or_identities(self):
        pack = _dominating_pack()
        assert pack.patterns, "the stored pack keeps its pattern aggregates"
        subset = build_interpretation_input(pack)
        assert subset.patterns == ()
        assert evidence_pack_to_payload(subset)["patterns"] == []
        # A model that cites an omitted pattern cannot validate against the
        # exact input it was given.
        with pytest.raises(ResearchInterpretationError):
            validate_interpretations(subset, InterpretationResult(
                ModelProvenance("test", "test-model"),
                (AIInterpretation("sample claim", (PatternCitation(ObservationType.TITLE_HAS_NUMERAL),)),),
            ))
        # ...while a retained text citation still validates.
        first = subset.analyses[0]
        ok = InterpretationResult(ModelProvenance("test", "test-model"), (AIInterpretation(
            "Grounded finding", (FactCitation(first.reference, EvidenceField.DESCRIPTION),),
        ),))
        assert validate_interpretations(subset, ok) is ok

    def test_model_can_cite_only_supplied_evidence(self):
        pack = _dominating_pack()
        subset = build_interpretation_input(pack)
        first = subset.analyses[0]
        provenance = ModelProvenance("test", "test-model")
        # A supplied title/description citation validates.
        ok = InterpretationResult(provenance, (AIInterpretation(
            "Grounded finding", (FactCitation(first.reference, EvidenceField.DESCRIPTION),),
        ),))
        assert validate_interpretations(subset, ok) is ok
        assert validate_text_supported_interpretations(subset, ok) is ok
        # A dropped field (engagement count) and a dropped reference cannot validate.
        with pytest.raises(ResearchInterpretationError):
            validate_interpretations(subset, InterpretationResult(provenance, (AIInterpretation(
                "x", (FactCitation(first.reference, EvidenceField.VIEW_COUNT),),
            ),)))
        dropped = [a for a in pack.analyses if a.reference not in {s.reference for s in subset.analyses}][0]
        with pytest.raises(ResearchInterpretationError):
            validate_interpretations(subset, InterpretationResult(provenance, (AIInterpretation(
                "x", (FactCitation(dropped.reference, EvidenceField.DESCRIPTION),),
            ),)))


class TestEndToEnd:
    def _service_with(self, respond):
        service = _report_service([])
        config = AIProviderConfig("fictional", "fictional-model", "https://fictional.invalid/chat", "fictional-test-key")
        service._interpretation = GroundedInterpretationService(  # noqa: SLF001 - test wiring
            OpenAICompatibleInterpretationProvider(config, transport=httpx.MockTransport(respond))
        )
        return service

    def test_research_only_sends_compact_input_once_and_keeps_full_evidence(self):
        sent: list[dict] = []

        def respond(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            evidence = json.loads(sent[-1]["messages"][1]["content"].split("\n\n", 1)[1])
            reference = evidence["references"][0]["reference_id"]
            content = {"interpretations": [{
                "statement": "A grounded finding about the supplied source.",
                "citations": [{"kind": "fact", "reference": reference, "field": "description"}],
            }]}
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})

        service = self._service_with(respond)
        report = service.build_report(**_query(), include_content_tools=False)

        assert len(sent) == 1, "exactly one AI request, no retry layer added"
        evidence = json.loads(sent[0]["messages"][1]["content"].split("\n\n", 1)[1])
        fields = {fact["field"] for analysis in evidence["references"] for fact in analysis["facts"]}
        assert fields == {"title", "description", "published_at", "channel_title"}
        assert "collected_at" not in sent[0]["messages"][1]["content"]
        assert report.interpretation_result.model_provenance.provider == "fictional"
        # The stored evidence pack keeps the full, original material, including
        # the patterns the compact input omits.
        assert len(report.evidence_pack.analyses) == len(report.research_run.references)
        assert all(analysis.observations for analysis in report.evidence_pack.analyses)
        assert report.evidence_pack.patterns


    def test_compacted_text_is_an_excerpt_and_stored_text_is_original(self):
        long_description = "A long source description that contains a qualification: this does not prove adoption. " * 20
        sent: list[dict] = []

        def respond(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            evidence = json.loads(sent[-1]["messages"][1]["content"].split("\n\n", 1)[1])
            reference = evidence["references"][0]["reference_id"]
            content = {"interpretations": [{
                "statement": "Grounded finding about the supplied source.",
                "citations": [{"kind": "fact", "reference": reference, "field": "description"}],
            }]}
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})

        service = self._service_with(respond)
        run = service._research.execute(**_query())  # noqa: SLF001 - test wiring
        run._references = tuple(replace(ref, description=long_description) for ref in run.references)  # noqa: SLF001
        service._research = SimpleNamespace(execute=lambda **kwargs: run)  # noqa: SLF001
        report = service.build_report(**_query(), include_content_tools=False)

        # What the model saw is an explicitly marked excerpt.
        evidence = json.loads(sent[0]["messages"][1]["content"].split("\n\n", 1)[1])
        described = next(fact["value"] for fact in evidence["references"][0]["facts"] if fact["field"] == "description")
        assert len(described) <= MAX_DESCRIPTION_CHARS + 1 and described.endswith("…")
        assert described != long_description

        # The stored pack and the saved snapshot keep the untouched original.
        stored = next(fact.value for fact in report.evidence_pack.analyses[0].facts if fact.field is EvidenceField.DESCRIPTION)
        assert stored == long_description
        snapshot = to_report_response(report).model_dump(mode="json", exclude={"persistence"})
        assert snapshot["research"]["references"][0]["description"] == long_description

        # The accepted citation still resolves to the original stored source text.
        citation = report.interpretation_result.interpretations[0].citations[0]
        assert citation.field is EvidenceField.DESCRIPTION
        assert report.evidence_pack.analyses[0].reference == citation.reference

    @pytest.mark.parametrize("mode", ["malformed", "pattern_only", "metric_only"])
    def test_rejected_or_unsupported_output_keeps_excerpt_fallback(self, mode):
        attempts = {"n": 0}

        def respond(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if mode == "malformed":
                content = {"interpretations": [{"statement": "x", "citations": [], "extra": 1}]}
            else:
                evidence = json.loads(json.loads(request.content)["messages"][1]["content"].split("\n\n", 1)[1])
                reference = evidence["references"][0]["reference_id"]
                if mode == "pattern_only":
                    cite = {"kind": "pattern", "observation_type": "title_has_numeral"}
                else:
                    cite = {"kind": "fact", "reference": reference, "field": "view_count"}
                content = {"interpretations": [{"statement": "sample shape claim", "citations": [cite]}]}
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})

        service = self._service_with(respond)
        report = service.build_report(**_query(), include_content_tools=False)
        assert report.interpretation_result.model_provenance.provider == "source_evidence"
        assert report.interpretation_result.interpretations
        # Malformed output keeps the pre-existing single bounded retry; a
        # structurally valid but unsupported finding falls back with no extra
        # call. Compaction adds no retry layer.
        assert attempts["n"] == (2 if mode == "malformed" else 1)


def _domain_ref(domain: str, slug: str, index: int) -> ResearchReference:
    """A public-web reference on an explicit domain, for ordering tests."""
    url = f"https://{domain}/{slug}-{index}"
    return ResearchReference(
        source_code="public_web", content_external_id=url,
        collected_at=datetime(2026, 10, 1, tzinfo=UTC), url=url,
        title=f"{slug} {index} on {domain}", description=f"Excerpt {index} on {domain}.",
        published_at=None, channel_title=domain, source_rank=index,
    )


def _selected_ids(analyses) -> list[str]:
    return [a.reference.content_external_id for a in analyses]


class TestSourceFairSelection:
    def test_web_first_domains_cannot_starve_youtube(self):
        refs = tuple(
            [_web_ref(i) for i in range(1, 26)]
            + [_youtube_reference(i) for i in range(1, 4)]
        )
        selected = select_analyses(analyze_references(refs), MAX_INPUT_REFERENCES)
        sources = [a.reference.source_code for a in selected]
        assert len(selected) == MAX_INPUT_REFERENCES
        assert sources.count("youtube") == 3, "the small source must keep all of its references"
        assert sources.count("public_web") == MAX_INPUT_REFERENCES - 3

    def test_youtube_first_domains_keep_every_web_domain(self):
        refs = tuple(
            [_youtube_reference(i) for i in range(1, 26)]
            + [_web_ref(i) for i in range(1, 4)]
        )
        selected = select_analyses(analyze_references(refs), MAX_INPUT_REFERENCES)
        domains = {a.reference.content_external_id.split("/")[2] for a in selected if a.reference.source_code == "public_web"}
        assert len(selected) == MAX_INPUT_REFERENCES
        assert domains == {"site1.example", "site2.example", "site3.example"}

    def test_more_domains_than_slots_is_deterministic_and_first_seen(self):
        refs = tuple(_web_ref(i) for i in range(1, 31))
        selected = select_analyses(analyze_references(refs), MAX_INPUT_REFERENCES)
        assert len(selected) == MAX_INPUT_REFERENCES
        assert _selected_ids(selected) == [f"https://site{i}.example/story" for i in range(1, 25)]

    def test_exhausted_source_redistributes_remaining_slots(self):
        refs = tuple(
            [_web_ref(1), _web_ref(2)]
            + [_youtube_reference(i) for i in range(1, 11)]
        )
        selected = select_analyses(analyze_references(refs), 6)
        sources = [a.reference.source_code for a in selected]
        assert len(selected) == 6
        assert sources.count("public_web") == 2
        assert sources.count("youtube") == 4

    def test_small_limits_follow_first_seen_source_order(self):
        refs = tuple(
            [_web_ref(1), _web_ref(2), _web_ref(3)]
            + [_youtube_reference(1)]
        )
        analyses = analyze_references(refs)
        assert [a.reference.source_code for a in select_analyses(analyses, 1)] == ["public_web"]
        assert [a.reference.source_code for a in select_analyses(analyses, 2)] == ["public_web", "youtube"]
        assert [a.reference.source_code for a in select_analyses(analyses, 3)] == ["public_web", "youtube", "public_web"]

    def test_nonpositive_limits_select_nothing(self):
        analyses = analyze_references((_web_ref(1), _youtube_reference(1)))
        assert select_analyses(analyses, 0) == ()
        assert select_analyses(analyses, -5) == ()

    def test_selection_is_deterministic(self):
        refs = tuple([_web_ref(i) for i in range(1, 9)] + [_youtube_reference(i) for i in range(1, 9)])
        analyses = analyze_references(refs)
        first = _selected_ids(select_analyses(analyses, 10))
        second = _selected_ids(select_analyses(analyses, 10))
        assert first == second and len(first) == 10

    def test_within_domain_reference_order_is_preserved(self):
        refs = tuple(
            [_domain_ref("d1.example", "a", i) for i in (1, 2, 3)]
            + [_domain_ref("d2.example", "b", i) for i in (4, 5, 6)]
        )
        selected = _selected_ids(select_analyses(analyze_references(refs), 4))
        assert selected == [
            "https://d1.example/a-1", "https://d2.example/b-4",
            "https://d1.example/a-2", "https://d2.example/b-5",
        ]

    def test_everything_that_fits_keeps_original_order(self):
        refs = tuple([_web_ref(i) for i in range(1, 6)] + [_youtube_reference(1)])
        analyses = analyze_references(refs)
        assert select_analyses(analyses, MAX_INPUT_REFERENCES) == analyses


class TestTruncationNeverBecomesEvidence:
    def test_whitespace_only_text_truncates_to_blank(self):
        for whitespace in (" " * 700, "\t\n" * 400, "\u00a0" * 700, "\u3000" * 700):
            assert truncate_text(whitespace, MAX_DESCRIPTION_CHARS) == "", repr(whitespace[:3])

    def test_long_whitespace_prefix_keeps_meaningful_text(self):
        assert truncate_text((" " * 700) + "real content", MAX_DESCRIPTION_CHARS) == "real content"

    def test_marker_only_appears_when_text_is_retained_and_omitted(self):
        assert not truncate_text("", MAX_DESCRIPTION_CHARS)
        assert not truncate_text("   ", MAX_DESCRIPTION_CHARS)
        assert not truncate_text((" " * 700) + "short tail", MAX_DESCRIPTION_CHARS).endswith("…")
        retained = truncate_text((" " * 700) + ("x" * 900), MAX_DESCRIPTION_CHARS)
        assert retained.endswith("…") and len(retained) <= MAX_DESCRIPTION_CHARS + 1
        assert truncate_text("y" * 900, MAX_DESCRIPTION_CHARS).endswith("…")

    def test_compact_input_keeps_whitespace_only_evidence_blank(self):
        blank = replace(_domain_ref("blank.example", "blank", 1), description=" " * 700)
        payload = evidence_pack_to_payload(build_interpretation_input(EvidencePack(analyze_references((blank,)))))
        described = next(fact["value"] for fact in payload["references"][0]["facts"] if fact["field"] == "description")
        assert described == ""

    def test_blank_evidence_cannot_become_an_accepted_finding(self):
        calls: list[int] = []

        def respond(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            evidence = json.loads(json.loads(request.content)["messages"][1]["content"].split("\n\n", 1)[1])
            blank = next(a for a in evidence["references"] if a["reference_id"]["content_external_id"].endswith("/blank"))
            content = {"interpretations": [{
                "statement": "A development supported only by blank evidence.",
                "citations": [{"kind": "fact", "reference": blank["reference_id"], "field": "description"}],
            }]}
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})

        blank = ResearchReference(
            source_code="public_web", content_external_id="https://blank.example/blank",
            collected_at=datetime(2026, 10, 1, tzinfo=UTC), url="https://blank.example/blank",
            title=None, description=" " * 700, published_at=None,
            channel_title="blank.example", source_rank=2,
        )
        service = _report_service([])
        run = service._research.execute(**_query())  # noqa: SLF001 - test wiring
        usable = replace(run.references[0], description="Usable source text describing a real development.")
        run._references = (usable, blank)  # noqa: SLF001
        service._research = SimpleNamespace(execute=lambda **kwargs: run)  # noqa: SLF001
        service._interpretation = GroundedInterpretationService(  # noqa: SLF001
            OpenAICompatibleInterpretationProvider(
                AIProviderConfig("fictional", "fictional-model", "https://fictional.invalid/chat", "k"),
                transport=httpx.MockTransport(respond),
            )
        )
        report = service.build_report(**_query(), include_content_tools=False)

        assert len(calls) == 1, "rejection must not add an AI request"
        assert report.interpretation_result.model_provenance.provider == "source_evidence", "excerpt fallback must remain"
        assert all("blank evidence" not in item.statement for item in report.interpretation_result.interpretations)
        assert report.interpretation_result.interpretations, "the usable source still yields labelled excerpts"
