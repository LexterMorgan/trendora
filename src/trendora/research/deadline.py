"""Monotonic AI-phase deadline (bounded reliability pass).

One shared, wall-clock budget for the whole AI phase of a report:
interpretation + its validation retry + optional strategy/ideation. Retries and
later stages consume the *same* remaining budget instead of restarting it.

Enforcement is a true wall-clock cancel: the transport runs each request with
``asyncio.wait_for`` over the whole exchange (connect + headers + body read), so
a response that keeps trickling small chunks past the deadline is actually
interrupted — not merely bounded per socket read. The async client's context
manager releases the connection when the task is cancelled; no worker thread is
abandoned.

Remaining ceiling: this bounds the AI phase only. Collection and persistence are
separate and the true end-to-end limit is still the outer HTTP caller (the Next
proxy's 180-second deadline). We do not claim those sums fit.
"""

from __future__ import annotations

import inspect
import time
from typing import Any, Callable, TypeVar

_T = TypeVar("_T")


def accepts_deadline(fn: Callable[..., Any]) -> bool:
    """True when ``fn`` declares a ``deadline`` keyword."""
    try:
        return "deadline" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def call_with_deadline(
    fn: Callable[..., _T], arg: Any, deadline: "AIPhaseDeadline | None"
) -> _T:
    """Call ``fn(arg)``, forwarding ``deadline`` when the caller set one.

    A configured budget MUST reach the callee: if ``deadline`` is set but the
    callee cannot accept it, this refuses rather than silently running the AI
    phase unbounded. When ``deadline`` is ``None`` the callee is called plainly
    (deadline-free mode).
    """
    if deadline is None:
        return fn(arg)
    if not accepts_deadline(fn):
        raise TypeError(
            f"{getattr(fn, '__qualname__', fn)!r} cannot accept the AI-phase "
            "deadline; refusing to run unbounded"
        )
    return fn(arg, deadline=deadline)


class AIPhaseDeadline:
    """A monotonic budget shared by every AI stage of one report.

    ``total_seconds`` is the AI-phase budget. The clock starts on construction
    (right before the AI phase) and never resets, so a retry sees the time the
    previous attempt already spent.
    """

    __slots__ = ("_total", "_start")

    def __init__(self, total_seconds: float) -> None:
        if total_seconds <= 0:
            raise ValueError("AI phase budget must be positive")
        self._total = float(total_seconds)
        self._start = time.monotonic()

    @property
    def total_seconds(self) -> float:
        return self._total

    def remaining(self) -> float:
        """Seconds left in the budget; may be <= 0 once exhausted."""
        return self._total - (time.monotonic() - self._start)

    def expired(self) -> bool:
        return self.remaining() <= 0.0
