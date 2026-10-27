"""Shared AI-phase deadline regressions (bounded reliability pass).

Fully offline. A controllable monotonic clock makes the shared budget
deterministic without real sleeps. The orchestrator threads one deadline
through interpretation, its malformed-output retry, and optional
strategy/ideation; retries and later stages consume the same remaining budget.
"""

from __future__ import annotations

import logging
import time

import httpx
import pytest

from trendora.research import (
    ResearchAIResponseError,
    ResearchAITimeoutError,
    ResearchReportService,
    ResearchReportStatus,
)
from trendora.research.deadline import AIPhaseDeadline, call_with_deadline
from trendora.research.reporting import (
    GroundedIdeationService,
    GroundedInterpretationService,
    GroundedStrategyService,
)
from tests.unit.test_research_reporting import (
    RecordingIdeationProvider,
    RecordingStrategyProvider,
    _query,
    _research,
    _text_supported_interpretation,
    _youtube_handler,
)


@pytest.fixture
def clock(monkeypatch):
    """Deterministic monotonic clock for trendora.research.deadline."""
    state = {"t": 1000.0}

    def monotonic() -> float:
        return state["t"]

    monkeypatch.setattr("trendora.research.deadline.time.monotonic", monotonic)
    return state


class _DeadlineAwareInterp:
    """A provider whose ``interpret`` is replaced per-test.

    Tracks call count and the remaining budget observed on each call.
    """

    def __init__(self):
        self.remaining_seen: list[float | None] = []
        self.calls = 0

    def interpret(self, pack, *, deadline=None):  # replaced by tests
        raise AssertionError("interpret must be assigned by the test")


def _service(interp, strategy=None, ideation=None, *, budget):
    return ResearchReportService(
        _research(_youtube_handler),
        GroundedInterpretationService(interp),
        GroundedStrategyService(strategy or RecordingStrategyProvider([])),
        GroundedIdeationService(ideation or RecordingIdeationProvider([])),
        ai_phase_budget_seconds=budget,
    )


class TestRetrySharesBudget:
    def test_retry_receives_only_remaining_time(self, clock):
        # First attempt consumes 10s of a 90s budget, then fails malformed.
        interp = _DeadlineAwareInterp()

        def interpret(pack, *, deadline=None):
            interp.calls += 1
            interp.remaining_seen.append(deadline.remaining() if deadline else None)
            if interp.calls == 1:
                clock["t"] += 10.0  # leave enough time for one bounded retry
                raise ResearchAIResponseError("bad")
            return _text_supported_interpretation(pack)

        interp.interpret = interpret
        report = _service(interp, budget=90.0).build_report(
            **_query(), include_content_tools=False
        )
        assert report.status is ResearchReportStatus.RESEARCH_COMPLETED
        assert interp.calls == 2
        # First attempt saw ~90s; the retry saw only the ~80s that remained.
        assert interp.remaining_seen[0] == pytest.approx(90.0, abs=0.01)
        assert interp.remaining_seen[1] == pytest.approx(80.0, abs=0.01)

    def test_expensive_failed_attempt_prevents_unchanged_retry(self, clock, caplog):
        import logging

        interp = _DeadlineAwareInterp()

        def fail(pack, *, deadline=None):
            interp.calls += 1
            clock["t"] += 80.0
            raise ResearchAIResponseError("bad")

        interp.interpret = fail
        with caplog.at_level(logging.WARNING, logger="trendora.research.reporting"):
            report = _service(interp, budget=90.0).build_report(
                **_query(), include_content_tools=False
            )
        assert report.status is ResearchReportStatus.RESEARCH_COMPLETED
        assert interp.calls == 1
        assert "reason=insufficient_budget_for_retry" in caplog.text

    def test_exhausted_budget_prevents_retry(self, clock):
        interp = _DeadlineAwareInterp()

        def fail(pack, *, deadline=None):
            interp.calls += 1
            clock["t"] += 90.0  # exhaust the whole budget
            raise ResearchAIResponseError("bad")

        interp.interpret = fail
        report = _service(interp, budget=90.0).build_report(
            **_query(), include_content_tools=False
        )
        # No second attempt: the malformed-output retry was refused.
        assert interp.calls == 1
        # Honest fallback preserved.
        assert report.status is ResearchReportStatus.RESEARCH_COMPLETED
        assert report.interpretation_result.model_provenance.provider == "source_evidence"


class TestOptionalStagesShareBudget:
    def test_content_stages_skipped_when_budget_exhausted(self, clock):
        events: list[str] = []
        interp_obj = _DeadlineAwareInterp()

        def interp(pack, *, deadline=None):
            interp_obj.calls += 1
            clock["t"] += 90.0  # interpretation alone exhausts the budget
            return _text_supported_interpretation(pack)

        interp_obj.interpret = interp
        strategy = RecordingStrategyProvider(events)
        ideation = RecordingIdeationProvider(events)
        report = _service(interp_obj, strategy, ideation, budget=90.0).build_report(
            **_query(), include_content_tools=True
        )
        # Strategy/ideation never ran: their budget was gone.
        assert events == []
        assert strategy.calls == 0 and ideation.calls == 0
        assert report.status is ResearchReportStatus.CONTENT_UNAVAILABLE

    def test_content_stages_run_within_remaining_budget(self, clock):
        events: list[str] = []
        interp_obj = _DeadlineAwareInterp()

        def interp(pack, *, deadline=None):
            interp_obj.calls += 1
            clock["t"] += 10.0  # leaves 80s
            return _text_supported_interpretation(pack)

        interp_obj.interpret = interp
        report = _service(
            interp_obj, RecordingStrategyProvider(events), RecordingIdeationProvider(events),
            budget=90.0,
        ).build_report(**_query(), include_content_tools=True)
        assert events == ["strategy", "ideation"]
        assert report.status is ResearchReportStatus.RESEARCH_COMPLETED


class TestTimeoutFallback:
    def test_timeout_retains_fallback_and_sanitized_log(self, clock, caplog):
        interp = _DeadlineAwareInterp()

        def timeout(pack, *, deadline=None):
            interp.calls += 1
            raise ResearchAITimeoutError("AI provider timed out after 90s (9router)")

        interp.interpret = timeout
        with caplog.at_level(logging.WARNING, logger="trendora.research.reporting"):
            report = _service(interp, budget=90.0).build_report(
                **_query(), include_content_tools=False
            )
        assert report.interpretation_result.model_provenance.provider == "source_evidence"
        assert "ResearchAITimeoutError" in caplog.text
        # No provider text, endpoint, or key leaks into logs.
        assert "9router" not in caplog.text
        assert "timed out" not in caplog.text


class TestNormalSuccess:
    def test_normal_text_supported_output_succeeds_under_deadline(self, clock):
        interp = _DeadlineAwareInterp()

        def ok(pack, *, deadline=None):
            interp.calls += 1
            return _text_supported_interpretation(pack)

        interp.interpret = ok
        report = _service(interp, budget=90.0).build_report(
            **_query(), include_content_tools=False
        )
        assert report.status is ResearchReportStatus.RESEARCH_COMPLETED
        assert report.interpretation_result.interpretations
        assert report.interpretation_result.model_provenance.provider != "source_evidence"


class TestDeadlinePrimitive:
    def test_remaining_decreases_monotonically(self, clock):
        d = AIPhaseDeadline(10.0)
        assert d.remaining() == pytest.approx(10.0)
        clock["t"] += 4.0
        assert d.remaining() == pytest.approx(6.0)
        assert not d.expired()
        clock["t"] += 6.0
        assert d.expired()

    def test_non_positive_budget_rejected(self):
        with pytest.raises(ValueError):
            AIPhaseDeadline(0)

    def test_call_with_deadline_forwards_when_accepted(self, clock):
        d = AIPhaseDeadline(30.0)
        seen = {}

        def with_kw(arg, *, deadline=None):
            seen["deadline"] = deadline
            return arg

        call_with_deadline(with_kw, "x", d)
        assert seen["deadline"] is d

    def test_call_with_deadline_refuses_a_callee_that_cannot_accept_it(self, clock):
        # A configured budget must not be silently dropped.
        d = AIPhaseDeadline(30.0)

        def without_kw(arg):
            return arg

        with pytest.raises(TypeError, match="deadline"):
            call_with_deadline(without_kw, "y", d)

    def test_call_with_deadline_none_runs_plainly(self, clock):
        seen = {}

        def without_kw(arg):
            seen["ran"] = arg
            return arg

        call_with_deadline(without_kw, "y", None)
        assert seen["ran"] == "y"


class TestSlowResponseCancellation:
    """Real loopback HTTP drip-feed proves wall-clock cancellation.

    The server sends a small chunk well within the per-read timeout but keeps
    streaming past the shared deadline. Only a true wall-clock cancel (async
    ``wait_for`` over the whole exchange) can stop this; an httpx per-operation
    timeout cannot. Uses the repo's ``permit_network`` for loopback only.
    """

    def _drip_server(self, *, chunk_gap: float, chunks: int):
        import select
        import socket
        import threading

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        state = {"connections": 0, "closed": False, "stop": False}

        def serve() -> None:
            conn, _ = srv.accept()
            state["connections"] += 1
            try:
                conn.recv(65536)
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    b"Transfer-Encoding: chunked\r\n\r\n"
                )
                for _ in range(chunks):
                    if state["stop"]:
                        break
                    time.sleep(chunk_gap)
                    c = b'{"x":1}'
                    conn.sendall(b"%x\r\n%s\r\n" % (len(c), c))
                    # Detect the peer's FIN between chunks (client cancellation).
                    ready, _, _ = select.select([conn], [], [], 0)
                    if ready and conn.recv(4096) == b"":
                        state["closed"] = True
                        return
                # Response not finished; keep the socket open so a
                # non-cancelling client would stall here.
                while not state["stop"]:
                    ready, _, _ = select.select([conn], [], [], 0.1)
                    if ready and conn.recv(4096) == b"":
                        state["closed"] = True
                        return
            except OSError:
                state["closed"] = True
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

        threading.Thread(target=serve, daemon=True).start()

        def shutdown() -> None:
            state["stop"] = True
            try:
                srv.close()
            except OSError:
                pass

        return port, shutdown, state

    def test_deadline_interrupts_in_flight_drip_feed(self):
        import time as _time

        from tests.io_guards import GUARDS
        from tests.unit.test_research_ai_provider import _pack
        from trendora.research.ai_provider import (
            AIProviderConfig,
            OpenAICompatibleInterpretationProvider,
        )

        # Each chunk arrives in 0.1s (well under the 30s read timeout); the full
        # response would need ~5s, far beyond the 1s shared deadline.
        port, shutdown, state = self._drip_server(chunk_gap=0.1, chunks=50)
        cfg = AIProviderConfig(
            provider="9router",
            model="free-models",
            endpoint_url=f"http://127.0.0.1:{port}/v1/chat/completions",
            api_key="k",
            timeout_seconds=30.0,
        )
        provider = OpenAICompatibleInterpretationProvider(cfg)
        deadline = AIPhaseDeadline(1.0)
        started = _time.monotonic()
        try:
            with GUARDS.permit_network():
                with pytest.raises(ResearchAITimeoutError):
                    provider.interpret(_pack(), deadline=deadline)
            elapsed = _time.monotonic() - started
        finally:
            shutdown()

        # Terminated near the 1s deadline, not at the ~5s full response.
        assert 0.5 <= elapsed <= 2.5, f"cancelled at {elapsed:.2f}s"
        # Exactly one in-flight request; the server saw the client disconnect.
        assert state["connections"] == 1
        for _ in range(50):
            if state["closed"]:
                break
            _time.sleep(0.05)
        assert state["closed"] is True
        # Budget consumed: no further stage can start.
        assert deadline.expired()

    def test_expired_budget_refuses_request_before_sending(self, clock):
        from tests.unit.test_research_ai_provider import _pack
        from trendora.research.ai_provider import (
            AIProviderConfig,
            OpenAICompatibleInterpretationProvider,
        )

        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"interpretations": []}'}}]})

        cfg = AIProviderConfig(
            provider="9router", model="free-models",
            endpoint_url="http://provider.test/v1/chat/completions", api_key="k",
        )
        provider = OpenAICompatibleInterpretationProvider(
            cfg, transport=httpx.MockTransport(handler)
        )
        d = AIPhaseDeadline(10.0)
        clock["t"] += 10.0  # exhausted
        with pytest.raises(ResearchAITimeoutError):
            provider.interpret(_pack(), deadline=d)
        assert calls["n"] == 0  # no request was sent
