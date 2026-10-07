"""Streamed request-body cap shared by routers that accept large writes.

The cap is enforced while reading, so a missing or understated
``Content-Length`` cannot get an oversized body past validation. Each router
subclasses :class:`BodyLimitRoute` with its own limit and error class; the
planner keeps its small draft cap, the report-save route allows a full report
envelope.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH"})


class BodyLimitRoute(APIRoute):
    """APIRoute that reads write bodies itself and enforces a byte cap."""

    body_limit: int = 0
    write_methods: frozenset[str] = _WRITE_METHODS

    def too_large(self) -> Exception:
        raise NotImplementedError

    def get_route_handler(self):  # type: ignore[no-untyped-def]
        original_handler = super().get_route_handler()
        limit = self.body_limit
        methods = self.write_methods

        async def bounded_handler(request: Request) -> Response:
            if request.method not in methods:
                return await original_handler(request)

            chunks: list[bytes] = []
            total = 0
            while True:
                message = await request.receive()
                if message["type"] != "http.request":
                    break
                body = message.get("body") or b""
                total += len(body)
                if total > limit:
                    raise self.too_large()
                chunks.append(body)
                if not message.get("more_body"):
                    break
            payload = b"".join(chunks)

            async def replay() -> dict[str, Any]:
                return {
                    "type": "http.request",
                    "body": payload,
                    "more_body": False,
                }

            return await original_handler(Request(request.scope, receive=replay))

        return bounded_handler
