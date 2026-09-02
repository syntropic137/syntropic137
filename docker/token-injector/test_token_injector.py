"""Unit tests for docker/token-injector/token_injector.py (issue #1080).

Pure logic tests - runs the real `TokenInjectorHandler` on a loopback socket
and issues real HTTP requests over the wire, no Docker. No `pytest.mark.unit`
convention exists for `docker/` yet; this follows the standalone-script test
convention used by `infra/scripts/tests/test_env_manager.py`.

The module is loaded via `importlib` from its file path rather than a
package-qualified `import` because `docker` is also the name of a real
installed package (docker-py, used elsewhere in this project); importing
this file as `docker.token_injector` would shadow that package on sys.path.
"""

from __future__ import annotations

import importlib.util
import socket
import sys
import threading
from http.server import HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

_MODULE_PATH = Path(__file__).parent / "token_injector.py"
_spec = importlib.util.spec_from_file_location("token_injector_under_test", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
token_injector = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = token_injector
_spec.loader.exec_module(token_injector)


def _raw_request(port: int, method: str, path: str, host_header: str) -> tuple[int, bytes]:
    """Send a raw HTTP/1.1 request and return (status_code, body_bytes).

    Uses a real socket instead of `http.client` because `http.client`
    silently discards the body of any HEAD response on the client side
    regardless of what the server actually put on the wire - which would
    hide the exact defect fixed here (the server writing a body it
    shouldn't for a HEAD request).
    """
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        request = f"{method} {path} HTTP/1.1\r\nHost: {host_header}\r\nConnection: close\r\n\r\n"
        sock.sendall(request.encode())
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    raw = b"".join(chunks)
    header_blob, _, body = raw.partition(b"\r\n\r\n")
    status_line = header_blob.split(b"\r\n", 1)[0]
    status_code = int(status_line.split(b" ")[1])
    return status_code, body


@pytest.fixture
def server_port(monkeypatch: pytest.MonkeyPatch) -> Iterator[int]:
    # A credential that could only appear in a response if this specific
    # request actually reached _handle_check() / _allow() - i.e. if the
    # method dispatch (do_HEAD/do_OPTIONS) exists and works.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-only-1080")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    token_injector.REGISTRY = token_injector._build_registry()

    httpd = HTTPServer(("127.0.0.1", 0), token_injector.TokenInjectorHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1]
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


class TestHeadAndOptionsMethods:
    """Envoy's ext_authz check forwards the original request method (#1080).

    Before the fix, TokenInjectorHandler defined only do_GET/do_POST, so
    BaseHTTPRequestHandler's default dispatch sent an unlogged 501 for any
    other verb - which Envoy's failure_mode_allow: false then turned into
    the bare 403 the CLI's HEAD preflight was hitting.
    """

    def test_head_reaches_the_credential_check_not_a_501(self, server_port: int) -> None:
        status, _ = _raw_request(server_port, "HEAD", "/api/hello", "envoy-proxy")
        assert status == 200

    def test_options_reaches_the_credential_check_not_a_501(self, server_port: int) -> None:
        status, _ = _raw_request(server_port, "OPTIONS", "/api/hello", "envoy-proxy")
        assert status == 200

    def test_head_injects_the_credential_header(self, server_port: int) -> None:
        with socket.create_connection(("127.0.0.1", server_port), timeout=5) as sock:
            sock.sendall(
                b"HEAD /api/hello HTTP/1.1\r\nHost: envoy-proxy\r\nConnection: close\r\n\r\n"
            )
            raw = b""
            while chunk := sock.recv(4096):
                raw += chunk
        header_blob = raw.partition(b"\r\n\r\n")[0].decode()
        assert "sk-test-only-1080" in header_blob

    def test_head_response_carries_no_body_even_when_denied(self, server_port: int) -> None:
        # Unregistered host -> _deny() -> 403. Per RFC 7231 4.3.2, a HEAD
        # response must never carry a body, even though the Content-Length
        # header (from the GET-equivalent response) is still reported.
        status, body = _raw_request(server_port, "HEAD", "/api/hello", "unknown-host.example")
        assert status == 403
        assert body == b""

    def test_get_response_to_the_same_denied_host_does_carry_a_body(self, server_port: int) -> None:
        # Control case: proves the HEAD test above is exercising the new
        # HEAD-specific branch, not just an empty _deny() body in general.
        status, body = _raw_request(server_port, "GET", "/api/hello", "unknown-host.example")
        assert status == 403
        assert body != b""
