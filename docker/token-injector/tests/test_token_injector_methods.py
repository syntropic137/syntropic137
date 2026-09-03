"""Every HTTP method must reach the allowlist check, not just GET and POST.

Envoy's ext_authz HTTP client copies the downstream request's ``:method`` onto
the check request it sends to the token injector. When the injector only
defined ``do_GET``/``do_POST``, every other verb hit BaseHTTPRequestHandler's
501 fallback, ext_authz classified the 5xx as ERROR, and ``failure_mode_allow:
false`` turned it into a bodyless 403 for the agent. That is what killed a
verify phase 948 seconds in: the Claude CLI probes connectivity with
``HEAD /api/hello`` (#1080).

These tests drive a real socket against a real HTTPServer, because the broken
hop was the handler *dispatch*, not the check itself - asserting on
``_handle_check`` directly would have passed throughout the outage.
"""

from __future__ import annotations

import socket
import threading
from dataclasses import dataclass
from http.server import HTTPServer
from typing import TYPE_CHECKING

import pytest
import token_injector

if TYPE_CHECKING:
    from collections.abc import Iterator

# CI runs `pytest -m unit`; without this the module collects zero tests there.
pytestmark = pytest.mark.unit

# Distinctive so it cannot be confused with a default or a placeholder: the
# production containers start agents with ANTHROPIC_API_KEY=proxy-managed and
# rely on the injector's response header to overwrite it.
_REAL_KEY = "sk-ant-test-1080-not-proxy-managed"
_ALLOWED_HOST = "envoy-proxy"
_BLOCKED_HOST = "evil.example.com"

# Everything an agent can send through the proxy. GET and POST are the two the
# injector used to answer; the rest are the regression.
_METHODS = ("GET", "POST", "HEAD", "OPTIONS", "PUT", "PATCH", "DELETE")


@dataclass(frozen=True)
class RawResponse:
    """A response read straight off the socket, so the body is what was sent."""

    status: int
    headers: dict[str, str]
    body: bytes


@pytest.fixture
def injector(monkeypatch: pytest.MonkeyPatch) -> Iterator[int]:
    """Run the real handler on a loopback port; yield that port."""
    monkeypatch.setattr(
        token_injector,
        "REGISTRY",
        {_ALLOWED_HOST: token_injector.ServiceEntry("anthropic", "x-api-key", _REAL_KEY)},
    )
    server = HTTPServer(("127.0.0.1", 0), token_injector.TokenInjectorHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request(port: int, method: str, host: str, path: str = "/api/hello") -> RawResponse:
    """Send one request and read to EOF, so a stray body cannot hide."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(f"{method} {path} HTTP/1.0\r\nHost: {host}\r\n\r\n".encode())
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)

    head, _, body = b"".join(chunks).partition(b"\r\n\r\n")
    status_line, *header_lines = head.decode("latin-1").split("\r\n")
    headers = {
        name.strip().lower(): value.strip()
        for name, _, value in (line.partition(":") for line in header_lines)
    }
    return RawResponse(int(status_line.split()[1]), headers, body)


@pytest.mark.parametrize("method", _METHODS)
def test_allowed_host_is_authorized_for_every_method(injector: int, method: str) -> None:
    """The verb must not change the decision - the allowlist keys on Host only."""
    response = _request(injector, method, _ALLOWED_HOST)

    assert response.status == 200, f"{method} was not authorized: {response.body!r}"
    # Envoy only forwards the credential on a 200, and only from this header.
    # A 200 with no x-api-key still breaks the agent: the upstream request goes
    # out carrying the "proxy-managed" placeholder.
    assert response.headers.get("x-api-key") == _REAL_KEY


@pytest.mark.parametrize("method", _METHODS)
def test_blocked_host_is_denied_for_every_method(injector: int, method: str) -> None:
    """A new verb must not become an accidental hole in the allowlist."""
    response = _request(injector, method, _BLOCKED_HOST)

    assert response.status == 403
    assert "x-api-key" not in response.headers


def test_head_denial_sends_headers_but_no_body(injector: int) -> None:
    """HEAD keeps the GET's headers and drops the body (RFC 9110 s9.3.2).

    Writing the body anyway would put the denial text on the wire where the
    next response belongs.
    """
    head = _request(injector, "HEAD", _BLOCKED_HOST)
    get = _request(injector, "GET", _BLOCKED_HOST)

    assert get.body == b"Host not allowed: " + _BLOCKED_HOST.encode()
    assert head.body == b""
    assert head.headers["content-length"] == get.headers["content-length"]


def test_head_reaches_the_check_and_is_logged(
    injector: int, caplog: pytest.LogCaptureFixture
) -> None:
    """The outage's other fingerprint: the injector logged nothing at all.

    The 501 fallback answers before ``_handle_check`` runs, so an operator
    grepping the injector log for the failing path finds no trace of it.
    """
    with caplog.at_level("INFO", logger=token_injector.logger.name):
        assert _request(injector, "HEAD", _ALLOWED_HOST, "/api/hello").status == 200

    assert "Auth check: host=envoy-proxy path=/api/hello" in caplog.text
