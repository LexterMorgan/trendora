"""Allowlisted, request-local measurements outside the immutable evidence snapshot."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import time


def _milliseconds(start: float) -> int:
    return max(0, round((time.monotonic() - start) * 1000))


def _token_count(value) -> int | None:
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


@dataclass
class AIRequestDetails:
    stage: str
    request_bytes: int
    started: float = field(default_factory=time.monotonic)
    elapsed_ms: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    def observe_usage(self, usage) -> None:
        if isinstance(usage, dict):
            self.prompt_tokens = _token_count(usage.get("prompt_tokens"))
            self.completion_tokens = _token_count(usage.get("completion_tokens"))
            self.total_tokens = _token_count(usage.get("total_tokens"))

    def as_dict(self) -> dict:
        return {name: getattr(self, name) for name in (
            "stage", "request_bytes", "elapsed_ms", "prompt_tokens",
            "completion_tokens", "total_tokens",
        )}


@dataclass
class RunDetails:
    started: float = field(default_factory=time.monotonic)
    stage_durations_ms: dict[str, int] = field(default_factory=dict)
    ai_requests: list[AIRequestDetails] = field(default_factory=list)
    retry_count: int = 0
    stage: str = "ai"

    def as_dict(self, finding_mode: str) -> dict:
        return {
            "elapsed_ms": _milliseconds(self.started),
            "stage_durations_ms": dict(self.stage_durations_ms),
            "ai_requests": [item.as_dict() for item in self.ai_requests],
            "retry_count": self.retry_count,
            "finding_mode": finding_mode,
        }


_current: ContextVar[RunDetails | None] = ContextVar("research_run_details", default=None)


@contextmanager
def collect_run_details():
    details = RunDetails()
    token = _current.set(details)
    try:
        yield details
    finally:
        _current.reset(token)


@contextmanager
def measure_stage(stage: str):
    details = _current.get()
    if details is None:
        yield
        return
    started, previous = time.monotonic(), details.stage
    details.stage = stage
    try:
        yield
    finally:
        details.stage_durations_ms[stage] = details.stage_durations_ms.get(stage, 0) + _milliseconds(started)
        details.stage = previous


@contextmanager
def measure_ai_request(request: dict):
    details = _current.get()
    if details is None:
        yield None
        return
    # Keep the size, never the prompt, source material, headers, or provider body.
    size = len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    item = AIRequestDetails(stage=details.stage, request_bytes=size)
    details.ai_requests.append(item)
    try:
        yield item
    finally:
        item.elapsed_ms = _milliseconds(item.started)


def record_retry() -> None:
    details = _current.get()
    if details is not None:
        details.retry_count += 1
