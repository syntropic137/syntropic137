"""Server-side scope enforcement for requests that came from a workspace (ADR-072).

The Envoy sidecar forwards workspace traffic for the platform host to this API
and OVERWRITES ``x-syn-workspace-ingress`` on every such request, so a request
carrying the header came from a workspace whatever the workspace sent. Every
one of them must present a platform token whose scope allows the route;
requests without the header come from the internal network and are untouched,
as they were before (ADR-059).

This runs before the startup gate and every router, so no route can be
reached from a workspace without passing it.

Two things the router does are mirrored here, or the boundary drifts from what
is actually routed:

- The scope is checked against the ROUTER-RELATIVE path. Uvicorn started with
  ``--root-path /api/v1`` (selfhost) hands over ``/api/v1/health``; the router
  strips the root path with Starlette's own rule, and so does this.
- A redirect the framework emits (``/health/`` -> ``/health``) is built from
  the API's own view of the URL, which has lost the ``/syn-platform/api/v1``
  prefix Envoy stripped. Same-host ``Location`` headers are rewritten back onto
  that prefix, so a client following one stays on the authenticated route.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from starlette._utils import get_route_path

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
        denial = await self._tokens.authorize(authorization, method, get_route_path(scope))
        if denial is None:
            await self._app(scope, receive, self._keep_redirects_on_platform(scope, send))
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

    def _keep_redirects_on_platform(self, scope: Scope, send: Send) -> Send:
        host = next((v.decode("latin-1") for n, v in scope["headers"] if n == b"host"), "")
        base = self._tokens.workspace_api_base_path

        async def rewriting_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [
                    (
                        name,
                        _onto_platform(value, scope, host, base) if name == b"location" else value,
                    )
                    for name, value in message.get("headers", [])
                ]
            await send(message)

        return rewriting_send


def _onto_platform(location: bytes, scope: Scope, host: str, base: str) -> bytes:
    """``location`` re-rooted on the workspace's API base, unless it leaves this host."""
    parts = urlsplit(location.decode("latin-1"))
    if parts.netloc and parts.netloc != host:
        return location
    route_path = get_route_path({**scope, "path": parts.path or "/"})
    return urlunsplit(("", "", base + route_path, parts.query, parts.fragment)).encode("latin-1")
