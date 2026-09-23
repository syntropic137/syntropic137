"""Token Injector Service for Envoy ext_authz HTTP mode (ISS-43).

This service runs alongside the Envoy proxy and:
1. Receives HTTP ext_authz requests from Envoy
2. Checks the destination host against the allowlist
3. Returns credential headers to inject via the HTTP response
4. Blocks requests to hosts not in the allowlist (returns 403)

Uses the HTTP ext_authz protocol (simpler than gRPC — no protobuf needed).
Envoy merges response headers into the upstream request, OVERWRITING any
existing header with the same name (e.g., replaces "proxy-managed" with
the real API key).

Runs as a plain HTTP server on port 9002.

Note: GitHub hosts are passthrough — agents receive installation tokens
during the setup phase (stored in ~/.git-credentials). The token injector
does NOT handle GitHub auth.

Environment:
    ANTHROPIC_API_KEY: Anthropic API key (used when CLAUDE_CODE_OAUTH_TOKEN not set)
    CLAUDE_CODE_OAUTH_TOKEN: OAuth token for Claude (takes priority over API key)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PORT = 9002


# ---------------------------------------------------------------------------
# Credential registry
# ---------------------------------------------------------------------------


@dataclass
class ServiceEntry:
    service_name: str
    header_name: str
    header_value: str


_ANTHROPIC_HOSTS = (
    "api.anthropic.com",
    "claude.ai",
    # When agents use ANTHROPIC_BASE_URL=http://envoy-proxy:8081,
    # requests arrive with Host: envoy-proxy (ISS-43).
    "envoy-proxy",
)


def _build_anthropic_entry() -> ServiceEntry | None:
    """Resolve Anthropic credential, preferring API key over OAuth token.

    Priority matters: agent containers are started with ANTHROPIC_API_KEY=proxy-managed
    so Claude Code sends x-api-key requests. The injected credential must also use
    x-api-key so Envoy overwrites the placeholder with the real key (ISS-43).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        return ServiceEntry("anthropic", "x-api-key", api_key)

    oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if oauth_token:
        return ServiceEntry("anthropic", "Authorization", f"Bearer {oauth_token}")

    logger.warning("No Anthropic credential (set ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN)")
    return None


def _build_registry() -> dict[str, ServiceEntry]:
    """Build host → ServiceEntry mapping from environment variables."""
    registry: dict[str, ServiceEntry] = {}

    anthropic_entry = _build_anthropic_entry()
    if anthropic_entry:
        for host in _ANTHROPIC_HOSTS:
            registry[host] = anthropic_entry

    return registry


REGISTRY = _build_registry()

# Passthrough hosts — allowed but no credential injection
PASSTHROUGH_HOSTS = {
    # GitHub — agents get installation tokens during setup phase
    "api.github.com",
    "github.com",
    "raw.githubusercontent.com",
    # Package registries
    "pypi.org",
    "files.pythonhosted.org",
    "registry.npmjs.org",
}


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class TokenInjectorHandler(BaseHTTPRequestHandler):
    """Handle ext_authz check requests from Envoy."""

    def log_message(self, fmt: str, *args: object) -> None:
        # Route access logs through Python logger
        logger.debug(fmt, *args)

    def __getattr__(self, name: str) -> Callable[[], None]:
        """Answer an ext_authz check for any HTTP method.

        ``http.server`` dispatches a request by looking up ``do_<METHOD>`` and
        replies 501 when it finds nothing. Envoy maps a 5xx from the check
        server to ``CheckStatus::Error``, which with ``failure_mode_allow:
        false`` becomes a bodyless 403 for the agent — and envoy forwards the
        DOWNSTREAM method on the check request, so the method the agent used is
        the method that has to be found here.

        Naming methods here would make this class a second method allowlist,
        invisible from envoy.yaml and needing to be kept in step with it. It
        drifted exactly that way (#1080): the virtual hosts match ``prefix:
        "/"`` with no method condition while only GET and POST could be
        answered, so the Claude CLI's ``HEAD /api/hello`` preflight killed
        phases that had run for minutes. The check reads the Host header and
        nothing else, so it is method-agnostic by construction; this makes the
        dispatch method-agnostic too, and there is no list left to drift.

        ``ci/fitness/infrastructure/test_proxy_method_agreement.py`` fails if
        envoy.yaml ever does start restricting methods, at which point this
        blanket answer would no longer be the matching contract.
        """
        if name.startswith("do_"):
            return self._handle_check
        raise AttributeError(name)

    def _handle_check(self) -> None:
        # Envoy forwards the original request's Host header
        host = self.headers.get("x-forwarded-host") or self.headers.get("host", "")
        # Strip port if present
        host = host.split(":")[0].lower()

        logger.info("Auth check: host=%s path=%s", host, self.path)

        if host in PASSTHROUGH_HOSTS:
            logger.info("Passthrough: %s", host)
            self._allow({})
            return

        entry = REGISTRY.get(host)
        if entry is None:
            logger.warning("Host not in allowlist: %s", host)
            self._deny(f"Host not allowed: {host}")
            return

        logger.info("Auth approved: host=%s service=%s", host, entry.service_name)
        self._allow({entry.header_name: entry.header_value})

    def _allow(self, inject_headers: dict[str, str]) -> None:
        self.send_response(200)
        for key, value in inject_headers.items():
            self.send_header(key, value)
        self.end_headers()

    def _deny(self, message: str) -> None:
        body = message.encode()
        self.send_response(403)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        # A response to HEAD carries the headers of the equivalent GET and no
        # body (RFC 9110 s9.3.2). Envoy would discard a stray one today, but
        # only because this server speaks HTTP/1.0 and closes the connection
        # after every response; on a kept-alive connection its HTTP/1 codec
        # reads those bytes as the start of the next response.
        if self.command != "HEAD":
            self.wfile.write(body)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Token injector starting on port %d", PORT)
    logger.info("Loaded %d service entries", len(REGISTRY))
    server = HTTPServer(("0.0.0.0", PORT), TokenInjectorHandler)
    server.serve_forever()
