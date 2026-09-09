"""The token injector must answer an ext_authz check for any HTTP method (#1080).

Envoy's HTTP ext_authz client forwards the *downstream* request's ``:method``
to the check server: ``allowed_headers`` is built with ``add_http_headers=true``
for an ``http_service`` config, which auto-includes ``:method``/``:path``/
``host`` (envoy ``check_request_utils.cc``), and the client then copies those
headers verbatim onto the check request (``ext_authz_http_impl.cc``). So a
``HEAD /api/hello`` from the Claude CLI arrives here as a HEAD.

Anything this handler cannot answer becomes a 501, and envoy maps a 5xx from
the check server to ``CheckStatus::Error`` -> a bodyless 403 for the agent
(``failure_mode_allow: false``). That is the exact failure in #1080.

These tests drive a real server over a real socket, because the defect lives in
``http.server``'s ``do_<METHOD>`` dispatch - not in anything observable on the
handler object itself.
"""

from __future__ import annotations

import http.client
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
    from types import ModuleType

API_KEY = "sk-test-not-a-real-key"

#: Methods envoy will route to us. Its virtual hosts match ``prefix: "/"`` with
#: no method condition, so this list is illustrative, not exhaustive - the
#: contract is "any method", which is what ``test_unknown_method_is_answered``
#: pins.
FORWARDED_METHODS = ("GET", "POST", "HEAD", "OPTIONS", "PUT", "PATCH", "DELETE")


@pytest.fixture(scope="module")
def injector(monkeypatch_session: pytest.MonkeyPatch) -> ModuleType:
    """Import token_injector.py by path with a credential in the environment.

    The module builds ``REGISTRY`` at import time, so the environment has to be
    set before the import rather than after it.
    """
    monkeypatch_session.setenv("ANTHROPIC_API_KEY", API_KEY)
    path = Path(__file__).resolve().parents[1] / "token_injector.py"
    spec = importlib.util.spec_from_file_location("token_injector_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def monkeypatch_session() -> Iterator[pytest.MonkeyPatch]:
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def server(injector: ModuleType) -> Iterator[tuple[str, int]]:
    httpd = HTTPServer(("127.0.0.1", 0), injector.TokenInjectorHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[0], httpd.server_address[1]
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _check(server: tuple[str, int], method: str, host: str) -> http.client.HTTPResponse:
    """Send one ext_authz check request, shaped the way envoy sends it."""
    conn = http.client.HTTPConnection(*server, timeout=5)
    # Envoy forwards the original Host as x-forwarded-host; the connection's own
    # Host header addresses the injector itself.
    conn.request(method, "/api/hello", headers={"x-forwarded-host": host})
    return conn.getresponse()


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize("method", FORWARDED_METHODS)
def test_every_method_gets_the_credential(server: tuple[str, int], method: str) -> None:
    """Every method envoy forwards must be authorized AND get the credential.

    Asserting only the status would pass a handler that answers the method but
    injects nothing - envoy copies ``x-api-key`` upstream, so that header is
    what the agent's request actually depends on.
    """
    response = _check(server, method, "envoy-proxy:8081")

    assert response.status == 200, (
        f"{method} check returned {response.status}; envoy turns a 5xx from the "
        f"check server into a bodyless 403 for the agent (#1080)"
    )
    assert response.getheader("x-api-key") == API_KEY


@pytest.mark.unit
def test_unknown_method_is_answered(server: tuple[str, int]) -> None:
    """The contract is "any method", not "these seven".

    Envoy's routes carry no method condition, so a method nobody has thought of
    yet still reaches the injector. Enumerating methods here is what created
    #1080 in the first place.
    """
    response = _check(server, "PROPFIND", "envoy-proxy:8081")

    assert response.status == 200
    assert response.getheader("x-api-key") == API_KEY


@pytest.mark.unit
def test_disallowed_host_is_still_denied(server: tuple[str, int]) -> None:
    """Answering every method must not turn the host allowlist off."""
    response = _check(server, "GET", "evil.example.com")

    assert response.status == 403
    assert b"evil.example.com" in response.read()


@pytest.mark.unit
@pytest.mark.parametrize("method", FORWARDED_METHODS)
def test_disallowed_host_is_denied_for_every_method(server: tuple[str, int], method: str) -> None:
    response = _check(server, method, "evil.example.com")

    assert response.status == 403


@pytest.mark.unit
def test_head_denial_sends_no_body(server: tuple[str, int]) -> None:
    """A HEAD response carries no body (RFC 9110 s9.3.2).

    Read raw off the socket rather than through ``http.client``, which would
    hide a stray body by not reading one. Envoy's HTTP/1 codec does the same:
    bytes after the headers of a HEAD response are parsed as the start of the
    NEXT response, desyncing a pooled connection.
    """
    host, port = server
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.sendall(b"HEAD /api/hello HTTP/1.0\r\nx-forwarded-host: evil.example.com\r\n\r\n")
        raw = b""
        while chunk := sock.recv(4096):
            raw += chunk

    head, separator, body = raw.partition(b"\r\n\r\n")
    assert separator, f"malformed response: {raw!r}"
    assert head.startswith(b"HTTP/1.0 403"), head
    # The headers still describe the body the equivalent GET would return...
    assert b"Content-Length: " in head
    # ...but no body is on the wire.
    assert body == b"", f"HEAD response carried {len(body)} bytes of body: {body!r}"
