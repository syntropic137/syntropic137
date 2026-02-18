"""Token Injector Service for Envoy ext_authz.

This service runs alongside the Envoy sidecar and:
1. Receives ext_authz requests from Envoy
2. Fetches tokens from Token Vending Service
3. Returns headers to inject (Authorization)
4. Checks spend budget before allowing requests

Runs as a gRPC server implementing Envoy's ext_authz protocol.

Usage:
    python token_injector.py

Environment:
    SYN_TOKEN_SERVICE_URL: URL of token vending service
    SYN_SPEND_SERVICE_URL: URL of spend tracker service
    SYN_EXECUTION_ID: Current execution ID
"""

from __future__ import annotations

import logging
import os
from concurrent import futures

import grpc
from envoy.service.auth.v3 import external_auth_pb2 as auth_pb2
from envoy.service.auth.v3 import external_auth_pb2_grpc as auth_grpc
from google.rpc import code_pb2, status_pb2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment configuration
TOKEN_SERVICE_URL = os.getenv("SYN_TOKEN_SERVICE_URL", "http://localhost:8080")
EXECUTION_ID = os.getenv("SYN_EXECUTION_ID", "")

# Host to token type mapping
HOST_TOKEN_MAP = {
    "api.anthropic.com": "anthropic",
    "api.github.com": "github",
}


class TokenInjectorService(auth_grpc.AuthorizationServicer):
    """Envoy ext_authz service for token injection."""

    def __init__(self) -> None:
        self.tokens: dict[str, str] = {}
        self._load_tokens()

    def _load_tokens(self) -> None:
        """Load tokens from environment (for local dev) or token service."""
        # In production, would fetch from Token Vending Service
        # For now, check environment variables
        # CLAUDE_CODE_OAUTH_TOKEN takes priority over ANTHROPIC_API_KEY
        if oauth_token := os.getenv("CLAUDE_CODE_OAUTH_TOKEN"):
            self.tokens["anthropic"] = oauth_token
            self.tokens["anthropic_auth_mode"] = "oauth"
            logger.info("Loaded Anthropic OAuth token from environment")
        elif anthropic_key := os.getenv("ANTHROPIC_API_KEY"):
            self.tokens["anthropic"] = anthropic_key
            self.tokens["anthropic_auth_mode"] = "api_key"
            logger.info("Loaded Anthropic API key from environment")

        if github_token := os.getenv("SYN_GITHUB_PRIVATE_KEY"):
            # Would generate installation token here
            self.tokens["github"] = github_token
            logger.info("Loaded GitHub credentials from environment")

    def Check(
        self, request: auth_pb2.CheckRequest, _context: grpc.ServicerContext
    ) -> auth_pb2.CheckResponse:
        """Handle ext_authz check request.

        Called by Envoy for each outbound request.
        """
        # Extract request info
        http_request = request.attributes.request.http
        host = http_request.host
        path = http_request.path
        method = http_request.method

        logger.info(f"Auth check: {method} {host}{path}")

        # Determine token type from host
        token_type = HOST_TOKEN_MAP.get(host.split(":")[0])

        if not token_type:
            # Unknown host - deny
            return self._deny("Host not in allowlist")

        # Check if we have a token
        token = self.tokens.get(token_type)
        if not token:
            return self._deny(f"No token available for {token_type}")

        # TODO: Check spend budget before allowing request
        # budget_ok = await self._check_budget(EXECUTION_ID, host, path)
        # if not budget_ok:
        #     return self._deny("Budget exhausted")

        # Build response with injected headers
        response = auth_pb2.CheckResponse()
        response.status.CopyFrom(status_pb2.Status(code=code_pb2.OK))

        # Inject authorization header
        ok_response = response.ok_response
        _ = ok_response.headers  # Headers are modified in-place below

        if token_type == "anthropic":
            auth_mode = self.tokens.get("anthropic_auth_mode", "api_key")
            if auth_mode == "oauth":
                # OAuth uses Authorization Bearer header
                header = ok_response.headers.add()
                header.header.key = "Authorization"
                header.header.value = f"Bearer {token}"
            else:
                # API key uses x-api-key header
                header = ok_response.headers.add()
                header.header.key = "x-api-key"
                header.header.value = token
        elif token_type == "github":
            # GitHub uses Authorization Bearer
            header = ok_response.headers.add()
            header.header.key = "Authorization"
            header.header.value = f"Bearer {token}"

        # Add execution ID header for tracing
        exec_header = ok_response.headers.add()
        exec_header.header.key = "X-AEF-Execution-ID"
        exec_header.header.value = EXECUTION_ID or "unknown"

        logger.info(f"Auth approved: {method} {host}{path}")
        return response

    def _deny(self, message: str) -> auth_pb2.CheckResponse:
        """Build a denial response."""
        logger.warning(f"Auth denied: {message}")

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
    logger.info(f"Execution ID: {EXECUTION_ID or 'not set'}")
    logger.info(f"Token Service URL: {TOKEN_SERVICE_URL}")

    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
