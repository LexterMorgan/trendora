"""Grounded report questions: request shape, strict parsing, one HTTP request.

Network is fully mocked. These tests prove the ask contract and its refusals;
they cannot prove a live model answers well.
"""

from __future__ import annotations

import json
import asyncio
from dataclasses import replace

import httpx
import pytest

from trendora.research import ResearchAIResponseError
from trendora.research.ai_provider import (
    ASK_SYSTEM_PROMPT,
    AIProviderConfig,
    OpenAICompatibleInterpretationProvider,
    build_ask_request,
)

CONTEXT = {
    "topic": "Fictional AI education topic",
    "date_from": "2026-08-01",
    "date_to": "2026-08-31",
    "status": "completed",
    "findings": [
        {
            "statement": "A fictional finding.",
            "citations": [
                {"source_code": "youtube", "content_external_id": "video-1"}
            ],
        }
    ],
    "sources": [
        {
            "source_code": "youtube",
            "content_external_id": "video-1",
            "title": "Fictional source title",
            "published_at": "2026-08-12T12:00:00Z",
            "description": "Fictional source description.",
        }
    ],
}
QUESTION = "What did the report find?"


def _config() -> AIProviderConfig:
    return AIProviderConfig(
        provider="fictional",
        model="fictional-ask-model",
        endpoint_url="https://fictional.invalid/v1/chat/completions",
        api_key="fictional-key",
    )


def _envelope(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"content": content},
                    "finish_reason": "stop",
                }
            ]
        },
    )


def _ask(handler):
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    provider = OpenAICompatibleInterpretationProvider(
        _config(), transport=httpx.MockTransport(respond)
    )
    return provider, calls


def test_build_ask_request_carries_prompt_question_json_context_and_model():
    request = build_ask_request(_config(), CONTEXT, QUESTION)

    assert request["model"] == "fictional-ask-model"
    assert len(request["messages"]) == 2
    assert request["messages"][0] == {
        "role": "system",
        "content": ASK_SYSTEM_PROMPT,
    }
    user_content = request["messages"][1]["content"]
    assert request["messages"][1]["role"] == "user"
    assert QUESTION in user_content
    serialized = json.dumps(CONTEXT, ensure_ascii=False, separators=(",", ":"))
    assert serialized in user_content
    assert json.loads(user_content.split("Report material:\n\n", 1)[1].split("\n\nQuestion: ", 1)[0]) == CONTEXT


def test_ask_rejects_non_json_output_after_one_request():
    provider, calls = _ask(lambda request: _envelope("not json at all"))

    with pytest.raises(ResearchAIResponseError) as excinfo:
        provider.ask(context=CONTEXT, question=QUESTION)

    assert excinfo.value.reason_code == "invalid_json"
    assert len(calls) == 1


def test_ask_rejects_a_blank_answer_after_one_request():
    provider, calls = _ask(
        lambda request: _envelope(
            json.dumps({"answer": "   \n ", "citations": []})
        )
    )

    with pytest.raises(ResearchAIResponseError) as excinfo:
        provider.ask(context=CONTEXT, question=QUESTION)

    assert excinfo.value.reason_code == "statement"
    assert len(calls) == 1


def test_ask_returns_answer_and_citation_dicts_from_the_envelope():
    content = json.dumps(
        {
            "answer": "  A grounded answer.  ",
            "citations": [
                {"source_code": "youtube", "content_external_id": "video-1"},
                {
                    "source_code": "public_web",
                    "content_external_id": "https://example.test/story",
                },
            ],
        }
    )
    provider, calls = _ask(lambda request: _envelope(content))

    answer, citations = provider.ask(context=CONTEXT, question=QUESTION)

    assert answer == "A grounded answer."
    assert citations == [
        {"source_code": "youtube", "content_external_id": "video-1"},
        {
            "source_code": "public_web",
            "content_external_id": "https://example.test/story",
        },
    ]
    assert len(calls) == 1


def test_ask_sends_one_configured_request_without_retrying_a_failure():
    provider, calls = _ask(lambda request: _envelope('{"answer":"ok","citations":[]}'))

    provider.ask(context=CONTEXT, question=QUESTION)

    assert len(calls) == 1
    sent = json.loads(calls[0].content)
    assert sent["model"] == "fictional-ask-model"
    assert sent["messages"][0]["content"] == ASK_SYSTEM_PROMPT
    assert QUESTION in sent["messages"][1]["content"]
    assert calls[0].headers["authorization"] == "Bearer fictional-key"


def test_ask_applies_a_wall_clock_budget_and_cancels_the_exchange():
    from trendora.research.exceptions import ResearchAITimeoutError

    cancelled = []
    calls = []

    async def slow_exchange(request):
        calls.append(request)
        try:
            await asyncio.sleep(5)
            return _envelope('{"answer":"late","citations":[]}')
        finally:
            cancelled.append(True)

    provider = OpenAICompatibleInterpretationProvider(
        replace(_config(), timeout_seconds=0.02), transport=httpx.MockTransport(slow_exchange),
    )
    with pytest.raises(ResearchAITimeoutError):
        provider.ask(context=CONTEXT, question=QUESTION)
    assert len(calls) == 1
    assert cancelled == [True]


def test_ask_does_not_replace_an_exhausted_caller_budget():
    from trendora.research.deadline import AIPhaseDeadline
    from trendora.research.exceptions import ResearchAITimeoutError

    provider, calls = _ask(lambda request: _envelope('{"answer":"late","citations":[]}'))
    deadline = AIPhaseDeadline(1)
    deadline._start -= 2
    with pytest.raises(ResearchAITimeoutError):
        provider.ask(context=CONTEXT, question=QUESTION, deadline=deadline)
    assert calls == []
