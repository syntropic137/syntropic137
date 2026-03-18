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

Environment:
    ANTHROPIC_API_KEY: Anthropic API key (used when CLAUDE_CODE_OAUTH_TOKEN not set)
    CLAUDE_CODE_OAUTH_TOKEN: OAuth token for Claude (takes priority over API key)
    SYN_GITHUB_PRIVATE_KEY: GitHub App private key / installation token
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer

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


def _build_registry() -> dict[str, ServiceEntry]:
    """Build host → ServiceEntry mapping from environment variables."""
    registry: dict[str, ServiceEntry] = {}

    # Anthropic: prefer API key, fall back to OAuth token.
    #
    # Priority matters: agent containers are started with ANTHROPIC_API_KEY=proxy-managed
    # so Claude Code sends x-api-key requests. The injected credential must also use
    # x-api-key so Envoy overwrites the placeholder with the real key (ISS-43).
    # If only CLAUDE_CODE_OAUTH_TOKEN is available (no API key), use Bearer auth —
    # but then agent env must not set ANTHROPIC_API_KEY (different placeholder strategy).
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()

    if api_key:
        entry: ServiceEntry | None = ServiceEntry("anthropic", "x-api-key", api_key)
    elif oauth_token:
        entry = ServiceEntry("anthropic", "Authorization", f"Bearer {oauth_token}")
    else:
        logger.warning("No Anthropic credential (set ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN)")
        entry = None

    if entry:
        for host in (
            "api.anthropic.com",
            "claude.ai",
            # When agents use ANTHROPIC_BASE_URL=http://syn-envoy-proxy:8081,
            # requests arrive with Host: syn-envoy-proxy (ISS-43).
            "syn-envoy-proxy",
        ):
            registry[host] = entry

    # GitHub: private key / installation token
    github_key = os.environ.get("SYN_GITHUB_PRIVATE_KEY", "").strip()
    if github_key:
        gh_entry = ServiceEntry("github", "Authorization", f"Bearer {github_key}")
        for host in ("api.github.com", "github.com"):
            registry[host] = gh_entry

    return registry


REGISTRY = _build_registry()

# Passthrough hosts — allowed but no credential injection
PASSTHROUGH_HOSTS = {
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

    def do_GET(self) -> None:
        self._handle_check()

    def do_POST(self) -> None:
        self._handle_check()

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
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Token injector starting on port %d", PORT)
    logger.info("Loaded %d service entries", len(REGISTRY))
    server = HTTPServer(("0.0.0.0", PORT), TokenInjectorHandler)
    server.serve_forever()
