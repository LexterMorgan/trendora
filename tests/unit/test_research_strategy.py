"""M21 content gap & opportunity contract + execution tests. Fully mocked."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from trendora.research import (
    AIInterpretation,
    ClaimType,
    ContentGap,
    EvidenceField,
    EvidencePack,
    FactCitation,
    GroundedInterpretationService,
    GroundedStrategyService,
    InterpretationResult,
    MarketBasis,
    ModelProvenance,
    ObservationCitation,
    ObservationType,
    OpenAICompatibleInterpretationProvider,
    OpenAICompatibleStrategyProvider,
    Opportunity,
    PatternCitation,
    ReferenceId,
    ResearchAIResponseError,
    ResearchInterpretationError,
    ResearchMetrics,
    ResearchReference,
    StrategicContext,
    StrategicResult,
    SYSTEM_STRATEGIC_PROMPT,
    aggregate_patterns,
    analyze_reference,
    build_grounded_strategy_request,
    validate_strategic_result,
)
from trendora.research.ai_provider import AIProviderConfig
from trendora.research.strategy import _parse_strategy_output

UTC = timezone.utc
FAKE_KEY = "super-secret-test-key"
ENDPOINT = "https://provider.test/v1/chat/completions"


def _reference(external: str, *, title: str, description: str | None = None) -> ResearchReference:
    return ResearchReference(
        source_code="youtube",
        content_external_id=external,
        collected_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        url=f"https://www.youtube.com/watch?v={external}",
        title=title,
        description=description,
        published_at=datetime(2026, 8, 1, 8, 0, tzinfo=UTC),
        channel_external_id="UCx",
        channel_title="Example Channel",
        market_context="SG",
        market_basis=MarketBasis.YOUTUBE_REGION_AVAILABILITY,
        source_rank=1,
        metrics=ResearchMetrics(view_count=100, like_count=None, comment_count=5),
    )


def _pack() -> EvidencePack:
    analyses = (
        analyze_reference(_reference("a", title="5 AI Tools", description="guide: https://example.com")),
        analyze_reference(_reference("b", title="How Students Use AI")),
    )
    return EvidencePack(analyses=analyses, patterns=aggregate_patterns(analyses))


def _interpretation_result() -> InterpretationResult:
    return InterpretationResult(
        model_provenance=ModelProvenance(provider="test", model="test-model"),
        interpretations=(
            AIInterpretation(
                "The analyzed titles use a mix of numbered and non-numbered framing.",
                (PatternCitation(observation_type=ObservationType.TITLE_HAS_NUMERAL),),
            ),
        ),
    )


def _context() -> StrategicContext:
    return StrategicContext(evidence_pack=_pack(), interpretation_result=_interpretation_result())


def _config(**overrides) -> AIProviderConfig:
    payload = dict(provider="test", model="test-model", endpoint_url=ENDPOINT, api_key=FAKE_KEY)
    payload.update(overrides)
    return AIProviderConfig(**payload)


def _strategy_provider(handler) -> OpenAICompatibleStrategyProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAICompatibleStrategyProvider(_config(), http_client=client)


def _envelope(model_json: str) -> dict:
    return {"choices": [{"message": {"content": model_json}}]}


def _model_output(gaps: list, opportunities: list) -> str:
    return json.dumps({"content_gaps": gaps, "opportunities": opportunities})


def _fact_citation(external: str = "a", field: str = "view_count") -> dict:
    return {"kind": "fact", "reference": {"source_code": "youtube", "content_external_id": external}, "field": field}


def _pattern_citation(obs: str = "title_has_numeral") -> dict:
    return {"kind": "pattern", "observation_type": obs}


def _gap(statement: str = "Limited beginner-oriented guidance within the analyzed set.", **kw) -> dict:
    base = {
        "statement": statement,
        "citations": [_pattern_citation()],
        "supporting_interpretation_indexes": [0],
    }
    base.update(kw)
    return base


def _opp(statement: str = "Explore beginner-oriented AI workflow education.", **kw) -> dict:
    base = {"statement": statement, "gap_indexes": [0], "citations": [_pattern_citation()]}
    base.update(kw)
    return base


class TestContentGap:
    def test_valid(self) -> None:
        gap = ContentGap("gap", (PatternCitation(ObservationType.TITLE_HAS_NUMERAL),), (0,))
        assert gap.claim_type is ClaimType.AI_INTERPRETATION

    def test_blank_statement_rejected(self) -> None:
        with pytest.raises(ResearchInterpretationError):
            ContentGap("  ", (PatternCitation(ObservationType.TITLE_HAS_NUMERAL),), (0,))

    def test_requires_citation(self) -> None:
        with pytest.raises(ResearchInterpretationError):
            ContentGap("gap", (), (0,))

    def test_requires_supporting_interpretation(self) -> None:
        with pytest.raises(ResearchInterpretationError):
            ContentGap("gap", (PatternCitation(ObservationType.TITLE_HAS_NUMERAL),), ())

    def test_duplicate_citation_rejected(self) -> None:
        citation = PatternCitation(ObservationType.TITLE_HAS_NUMERAL)
        with pytest.raises(ResearchInterpretationError):
            ContentGap("gap", (citation, citation), (0,))

    def test_duplicate_index_rejected(self) -> None:
        with pytest.raises(ResearchInterpretationError):
            ContentGap("gap", (PatternCitation(ObservationType.TITLE_HAS_NUMERAL),), (0, 0))

    def test_negative_index_rejected(self) -> None:
        with pytest.raises(ResearchInterpretationError):
            ContentGap("gap", (PatternCitation(ObservationType.TITLE_HAS_NUMERAL),), (-1,))

    def test_claim_type_cannot_be_overridden(self) -> None:
        with pytest.raises(TypeError):
            ContentGap(
                "gap",
                (PatternCitation(ObservationType.TITLE_HAS_NUMERAL),),
                (0,),
                claim_type=ClaimType.RECOMMENDATION,
            )

    def test_immutable(self) -> None:
        gap = ContentGap("gap", (PatternCitation(ObservationType.TITLE_HAS_NUMERAL),), (0,))
        with pytest.raises(AttributeError):
            gap.statement = "changed"  # type: ignore[misc]


class TestOpportunity:
    def test_valid(self) -> None:
        opp = Opportunity("opp", (0,), (PatternCitation(ObservationType.TITLE_HAS_NUMERAL),))
        assert opp.claim_type is ClaimType.RECOMMENDATION

    def test_requires_gap_index(self) -> None:
        with pytest.raises(ResearchInterpretationError):
            Opportunity("opp", (), (PatternCitation(ObservationType.TITLE_HAS_NUMERAL),))

    def test_requires_citation(self) -> None:
        with pytest.raises(ResearchInterpretationError):
            Opportunity("opp", (0,), ())

    def test_duplicate_gap_index_rejected(self) -> None:
        with pytest.raises(ResearchInterpretationError):
            Opportunity("opp", (0, 0), (PatternCitation(ObservationType.TITLE_HAS_NUMERAL),))

    def test_negative_gap_index_rejected(self) -> None:
        with pytest.raises(ResearchInterpretationError):
            Opportunity("opp", (-1,), (PatternCitation(ObservationType.TITLE_HAS_NUMERAL),))

    def test_claim_type_cannot_be_overridden(self) -> None:
        with pytest.raises(TypeError):
            Opportunity(
                "opp",
                (0,),
                (PatternCitation(ObservationType.TITLE_HAS_NUMERAL),),
                claim_type=ClaimType.AI_INTERPRETATION,
            )


class TestStrategicContextAndValidation:
    def test_context_requires_grounded_interpretations(self) -> None:
        pack = _pack()
        ungrounded = InterpretationResult(
            model_provenance=ModelProvenance(provider="test", model="m"),
            interpretations=(
                AIInterpretation(
                    "fabricated",
                    (FactCitation(reference=ReferenceId("youtube", "zzz"), field=EvidenceField.VIEW_COUNT),),
                ),
            ),
        )
        with pytest.raises(ResearchInterpretationError):
            StrategicContext(evidence_pack=pack, interpretation_result=ungrounded)

    def _valid_result(self) -> StrategicResult:
        context = _context()
        gap = ContentGap(
            "Limited beginner-oriented guidance.",
            (PatternCitation(ObservationType.TITLE_HAS_NUMERAL),),
            (0,),
        )
        opp = Opportunity(
            "Explore beginner-oriented AI workflow education.",
            (0,),
            (PatternCitation(ObservationType.TITLE_HAS_NUMERAL),),
        )
        return StrategicResult(
            model_provenance=ModelProvenance(provider="test", model="test-model"),
            content_gaps=(gap,),
            opportunities=(opp,),
        )

    def test_valid_full_chain(self) -> None:
        result = self._valid_result()
        assert validate_strategic_result(_context(), result) is result

    def test_invalid_citation_fails(self) -> None:
        gap = ContentGap(
            "gap",
            (FactCitation(reference=ReferenceId("youtube", "zzz"), field=EvidenceField.VIEW_COUNT),),
            (0,),
        )
        result = StrategicResult(
            model_provenance=ModelProvenance(provider="test", model="m"),
            content_gaps=(gap,),
            opportunities=(),
        )
        with pytest.raises(ResearchInterpretationError):
            validate_strategic_result(_context(), result)

    def test_invalid_interpretation_index_fails(self) -> None:
        gap = ContentGap(
            "gap",
            (PatternCitation(ObservationType.TITLE_HAS_NUMERAL),),
            (9,),
        )
        result = StrategicResult(
            model_provenance=ModelProvenance(provider="test", model="m"),
            content_gaps=(gap,),
            opportunities=(),
        )
        with pytest.raises(ResearchInterpretationError, match="interpretation index 9"):
            validate_strategic_result(_context(), result)

    def test_invalid_gap_index_fails(self) -> None:
        result = StrategicResult(
            model_provenance=ModelProvenance(provider="test", model="m"),
            content_gaps=(
                ContentGap("g", (PatternCitation(ObservationType.TITLE_HAS_NUMERAL),), (0,)),
            ),
            opportunities=(
                Opportunity("o", (7,), (PatternCitation(ObservationType.TITLE_HAS_NUMERAL),)),
            ),
        )
        with pytest.raises(ResearchInterpretationError, match="gap index 7"):
            validate_strategic_result(_context(), result)

    def test_deterministic_outcome_and_no_mutation(self) -> None:
        context = _context()
        result = self._valid_result()
        first = validate_strategic_result(context, result)
        second = validate_strategic_result(context, result)
        assert first == second
        assert context.evidence_pack.analyses[0].facts  # unchanged, no error


class TestStrategyProvider:
    def test_valid_execution_with_gap_and_opportunity(self) -> None:
        context = _context()

        def handler(request: httpx.Request) -> httpx.Response:
            output = _model_output([_gap()], [_opp()])
            return httpx.Response(200, json=_envelope(output))

        provider = _strategy_provider(handler)
        result = provider.generate(context)
        assert result.model_provenance == ModelProvenance(provider="test", model="test-model")
        assert len(result.content_gaps) == 1
        assert len(result.opportunities) == 1
        assert result.opportunities[0].claim_type is ClaimType.RECOMMENDATION

    def test_empty_gaps_and_opportunities_valid(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope(_model_output([], [])))

        result = _strategy_provider(handler).generate(_context())
        assert result.content_gaps == ()
        assert result.opportunities == ()

    def test_gaps_without_opportunities_valid(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope(_model_output([_gap()], [])))

        result = _strategy_provider(handler).generate(_context())
        assert len(result.content_gaps) == 1
        assert result.opportunities == ()

    def test_opportunity_requires_gap_index_via_grounding(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_envelope(_model_output([_gap()], [_opp(gap_indexes=[5])])),
            )

        result = _strategy_provider(handler).generate(_context())
        assert result.opportunities[0].gap_indexes == (5,)
        with pytest.raises(ResearchInterpretationError):
            validate_strategic_result(_context(), result)

    def test_provenance_from_config_only(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            payload = _envelope(_model_output([], []))
            payload["model"] = "attacker-model"
            return httpx.Response(200, json=payload)

        provider = _strategy_provider(handler)
        assert provider.generate(_context()).model_provenance.model == "test-model"

    def test_http_failure_is_provider_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={})

        from trendora.research import ResearchAIProviderError

        with pytest.raises(ResearchAIProviderError):
            _strategy_provider(handler).generate(_context())

    def test_request_body_shape_and_secret_absence(self) -> None:
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            captured["authorization"] = request.headers.get("authorization")
            return httpx.Response(200, json=_envelope(_model_output([], [])))

        _strategy_provider(handler).generate(_context())
        body = captured["body"]
        assert body["model"] == "test-model"
        assert [m["role"] for m in body["messages"]] == ["system", "user"]
        assert body["max_tokens"] == 4096
        assert body["response_format"] == {"type": "json_object"}
        assert body["stream"] is False
        assert "reasoning" not in body
        user_content = body["messages"][1]["content"]
        for marker in ("Evidence:", "Interpretations:"):
            assert marker in user_content
        assert FAKE_KEY not in json.dumps(body)
        assert captured["authorization"] == f"Bearer {FAKE_KEY}"


class TestStrategyStrictParsing:
    def test_parse_strategy_output_valid(self) -> None:
        parsed = _parse_strategy_output(_model_output([_gap()], [_opp()]))
        assert len(parsed.content_gaps) == 1
        assert len(parsed.opportunities) == 1

    @pytest.mark.parametrize(
        "content",
        [
            "prose",
            "{bad",
            "```json\n{\"content_gaps\":[]}\n```",
            "pre {\"content_gaps\":[]}",
            "{\"content_gaps\":[]} post",
        ],
    )
    def test_malformed_json(self, content: str) -> None:
        with pytest.raises(ResearchAIResponseError):
            _parse_strategy_output(content)

    @pytest.mark.parametrize(
        "gaps,opps",
        [
            ([{"statement": "x", "citations": [_pattern_citation()], "supporting_interpretation_indexes": [0], "score": 5}], []),
            ([{"statement": "x", "citations": [_pattern_citation()], "supporting_interpretation_indexes": [0], "claim_type": "fact"}], []),
            ([{"statement": "x", "citations": [_pattern_citation()], "supporting_interpretation_indexes": [0], "provider": "p"}], []),
            ([{"statement": "x", "citations": [_pattern_citation()], "supporting_interpretation_indexes": [0], "idea": "make it"}], []),
        ],
    )
    def test_invalid_gaps(self, gaps, opps) -> None:
        with pytest.raises(ResearchAIResponseError):
            _parse_strategy_output(json.dumps({"content_gaps": gaps, "opportunities": opps}))

    @pytest.mark.parametrize(
        "gaps,opps",
        [
            ([_gap()], [{"statement": "x", "gap_indexes": [0], "citations": [_pattern_citation()], "brief": "b"}]),
            ([_gap()], [{"statement": "x", "gap_indexes": [0], "citations": [_pattern_citation()], "confidence": 0.9}]),
        ],
    )
    def test_invalid_opportunities(self, gaps, opps) -> None:
        with pytest.raises(ResearchAIResponseError):
            _parse_strategy_output(json.dumps({"content_gaps": gaps, "opportunities": opps}))

    @pytest.mark.parametrize(
        "gaps,opps",
        [
            ([{"statement": "x", "citations": [], "supporting_interpretation_indexes": [0]}], []),
            ([{"statement": "  ", "citations": [_pattern_citation()], "supporting_interpretation_indexes": [0]}], []),
            ([{"statement": "x", "citations": [_pattern_citation()], "supporting_interpretation_indexes": []}], []),
            ([{"statement": "x", "citations": [_pattern_citation()], "supporting_interpretation_indexes": [-1]}], []),
            ([_gap()], [{"statement": "x", "gap_indexes": [], "citations": [_pattern_citation()]}]),
            ([_gap()], [{"statement": "x", "gap_indexes": [-1], "citations": [_pattern_citation()]}]),
            ([_gap()], [{"statement": "x", "gap_indexes": [0], "citations": []}]),
        ],
    )
    def test_structural_invalid_via_provider(self, gaps, opps) -> None:
        # DTO accepts these; domain conversion rejects them.

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=_envelope(json.dumps({"content_gaps": gaps, "opportunities": opps}))
            )

        with pytest.raises(ResearchAIResponseError):
            _strategy_provider(handler).generate(_context())

    def test_unknown_top_level_field(self) -> None:
        with pytest.raises(ResearchAIResponseError):
            _parse_strategy_output(json.dumps({"content_gaps": [], "opportunities": [], "extra": 1}))


class TestEndToEnd:
    def test_full_pipeline(self) -> None:
        pack = _pack()

        # M20 grounded interpretation (mocked).
        def interpretation_handler(request: httpx.Request) -> httpx.Response:
            interp_json = json.dumps(
                {
                    "interpretations": [
                        {"statement": "mix of numbered framing", "citations": [_pattern_citation()]}
                    ]
                }
            )
            return httpx.Response(200, json=_envelope(interp_json))

        interp_provider = OpenAICompatibleInterpretationProvider(
            _config(), http_client=httpx.Client(transport=httpx.MockTransport(interpretation_handler))
        )
        interpretation_result = GroundedInterpretationService(interp_provider).interpret(pack)
        context = StrategicContext(evidence_pack=pack, interpretation_result=interpretation_result)

        # M21 strategy (mocked).
        def strategy_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope(_model_output([_gap()], [_opp()])))

        strategy_provider = OpenAICompatibleStrategyProvider(
            _config(), http_client=httpx.Client(transport=httpx.MockTransport(strategy_handler))
        )
        result = GroundedStrategyService(strategy_provider).generate(context)
        assert len(result.content_gaps) == 1
        assert len(result.opportunities) == 1

    def test_prompt_contains_strategy_boundaries(self) -> None:
        prompt = SYSTEM_STRATEGIC_PROMPT.lower()
        for boundary in [
            "within the analyzed reference set",
            "do not claim market-wide absence",
            "do not claim platform-wide absence",
            "creator nationality",
            "transcript",
            "performance",
            "content ideas",
            "expected performance",
            "output strict json only",
            "untrusted data",
        ]:
            assert boundary in prompt
