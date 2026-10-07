"""Server-side scope enforcement for requests that came from a workspace (ADR-072).

The Envoy sidecar forwards workspace traffic for the platform host to this API
and OVERWRITES ``x-syn-workspace-ingress`` on every such request, so a request
carrying the header came from a workspace whatever the workspace sent. Every
one of them must present a platform token whose scope allows the route;
requests without the header come from the internal network and are untouched,
as they were before (ADR-059).

This runs before the startup gate and every router, so no route can be
reached from a workspace without passing it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

    from syn_adapters.platform_access import PlatformTokenService

WORKSPACE_INGRESS_HEADER = b"x-syn-workspace-ingress"


class WorkspaceIngressMiddleware:
    """Refuse workspace-ingress requests that lack a token scoped for the route."""

    def __init__(self, app: ASGIApp, *, tokens: PlatformTokenService) -> None:
        self._app = app
        self._tokens = tokens

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return
        headers: list[tuple[bytes, bytes]] = scope["headers"]
        if not any(name == WORKSPACE_INGRESS_HEADER for name, _ in headers):
            await self._app(scope, receive, send)
            return
        authorization = next(
            (value.decode("latin-1") for name, value in headers if name == b"authorization"),
            None,
        )
        method = scope.get("method", "GET") if scope["type"] == "http" else "WEBSOCKET"
        denial = await self._tokens.authorize(authorization, method, scope["path"])
        if denial is None:
            await self._app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps({"detail": denial.reason}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": denial.status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
