"""Token Injector Service for Envoy ext_authz (ISS-43).

This service runs alongside the Envoy proxy and:
1. Receives ext_authz requests from Envoy
2. Looks up credentials from its own environment variables
3. Returns headers to inject (Authorization / x-api-key)
4. Blocks requests to hosts not in the allowlist

Runs as a gRPC server implementing Envoy's ext_authz protocol.

Usage:
    python token_injector.py

Environment:
    ANTHROPIC_API_KEY: Anthropic API key (used when CLAUDE_CODE_OAUTH_TOKEN not set)
    CLAUDE_CODE_OAUTH_TOKEN: OAuth token for Claude (takes priority)
    SYN_GITHUB_PRIVATE_KEY: GitHub App private key / installation token
    SYN_EXECUTION_ID: Execution ID for tracing headers
"""

from __future__ import annotations

import logging
import os
from concurrent import futures
from dataclasses import dataclass

import grpc
from envoy.service.auth.v3 import external_auth_pb2 as auth_pb2
from envoy.service.auth.v3 import external_auth_pb2_grpc as auth_grpc
from google.rpc import code_pb2, status_pb2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EXECUTION_ID = os.getenv("SYN_EXECUTION_ID", "")

# Hosts allowed through without credential injection (package registries, etc.)
PASSTHROUGH_HOSTS: frozenset[str] = frozenset(
    {
        "pypi.org",
        "files.pythonhosted.org",
        "registry.npmjs.org",
    }
)


@dataclass(frozen=True)
class ServiceEntry:
    """Resolved credential entry for a host."""

    service_name: str
    header_name: str
    header_value: str


def _build_service_registry() -> dict[str, ServiceEntry]:
    """Build host → ServiceEntry mapping from environment variables.

    Reads credentials from the proxy container's own environment.
    Each entry maps a hostname to the header that should be injected.
    """
    registry: dict[str, ServiceEntry] = {}

    # Anthropic: CLAUDE_CODE_OAUTH_TOKEN takes priority over ANTHROPIC_API_KEY
    oauth_token = os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if oauth_token:
        registry["api.anthropic.com"] = ServiceEntry(
            service_name="anthropic",
            header_name="Authorization",
            header_value=f"Bearer {oauth_token}",
        )
        logger.info("Loaded Anthropic OAuth token from environment")
    elif api_key:
        registry["api.anthropic.com"] = ServiceEntry(
            service_name="anthropic",
            header_name="x-api-key",
            header_value=api_key,
        )
        logger.info("Loaded Anthropic API key from environment")

    # GitHub: private key or installation token
    github_key = os.getenv("SYN_GITHUB_PRIVATE_KEY")
    if github_key:
        for host in ("api.github.com", "github.com", "raw.githubusercontent.com"):
            registry[host] = ServiceEntry(
                service_name="github",
                header_name="Authorization",
                header_value=f"Bearer {github_key}",
            )
        logger.info("Loaded GitHub credentials from environment")

    return registry


class TokenInjectorService(auth_grpc.AuthorizationServicer):
    """Envoy ext_authz service for credential injection."""

    def __init__(self) -> None:
        self._registry = _build_service_registry()

    def Check(
        self, request: auth_pb2.CheckRequest, _context: grpc.ServicerContext
    ) -> auth_pb2.CheckResponse:
        """Handle ext_authz check request from Envoy."""
        http_request = request.attributes.request.http
        host = http_request.host.split(":")[0]
        path = http_request.path
        method = http_request.method

        logger.info("Auth check: %s %s%s", method, host, path)

        # Passthrough hosts — allow without credential injection
        if host in PASSTHROUGH_HOSTS:
            logger.info("Passthrough: %s %s%s", method, host, path)
            return self._allow()

        # Look up service entry for this host
        entry = self._registry.get(host)
        if entry is None:
            return self._deny(f"Host not in allowlist: {host}")

        # Build response with injected credential header
        response = auth_pb2.CheckResponse()
        response.status.CopyFrom(status_pb2.Status(code=code_pb2.OK))

        ok_response = response.ok_response
        header = ok_response.headers.add()
        header.header.key = entry.header_name
        header.header.value = entry.header_value
        # OVERWRITE_IF_EXISTS_OR_ADD (2): replaces the placeholder "proxy-managed"
        # key that Claude Code sends with the real credential (ISS-43).
        header.append_action = 2

        # Add execution ID header for tracing
        exec_header = ok_response.headers.add()
        exec_header.header.key = "X-Syn-Execution-ID"
        exec_header.header.value = EXECUTION_ID or "unknown"

        logger.info("Auth approved: %s %s%s (service=%s)", method, host, path, entry.service_name)
        return response

    @staticmethod
    def _allow() -> auth_pb2.CheckResponse:
        """Build an allow response (no credential injection)."""
        response = auth_pb2.CheckResponse()
        response.status.CopyFrom(status_pb2.Status(code=code_pb2.OK))
        return response

    @staticmethod
    def _deny(message: str) -> auth_pb2.CheckResponse:
        """Build a denial response."""
        logger.warning("Auth denied: %s", message)
        response = auth_pb2.CheckResponse()
        response.status.CopyFrom(
            status_pb2.Status(
                code=code_pb2.PERMISSION_DENIED,
                message=message,
            )
        )
        return response


def serve() -> None:
    """Start the gRPC server."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    auth_grpc.add_AuthorizationServicer_to_server(TokenInjectorService(), server)
    server.add_insecure_port("[::]:9002")

    logger.info("Token Injector starting on port 9002")
    logger.info("Execution ID: %s", EXECUTION_ID or "not set")

    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
