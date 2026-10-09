"""The guard's HTTP front: a refused create never reaches the daemon, an allowed one is replayed."""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer

import pytest

from syn_adapters.docker_create_guard.policy import CreatePolicy
from syn_adapters.docker_create_guard.server import DockerSocket, make_handler
from .test_policy import ROOT, sidecar_body, workspace_body

pytestmark = pytest.mark.unit


class _FakeDaemon(DockerSocket):
    def __init__(self) -> None:
        super().__init__("/nonexistent")
        self.creates: list[tuple[str, bytes]] = []

    def request(
        self, method: str, path: str, body: bytes | None, headers: dict[str, str]
    ) -> tuple[int, list[tuple[str, str]], bytes]:
        self.creates.append((path, body or b""))
        return 201, [("Content-Type", "application/json"), ("Api-Version", "1.47")], b'{"Id":"abc","Warnings":[]}'


@pytest.fixture
def guard() -> Iterator[tuple[int, _FakeDaemon]]:
    daemon = _FakeDaemon()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(CreatePolicy(workspace_root=ROOT), daemon))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], daemon
    server.shutdown()


def _post(port: int, path: str, body: object) -> tuple[int, dict[str, object]]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", path, body=json.dumps(body), headers={"Content-Type": "application/json"})
    response = conn.getresponse()
    return response.status, json.loads(response.read())


def test_allowed_create_is_replayed_with_its_query(guard: tuple[int, _FakeDaemon]) -> None:
    port, daemon = guard
    status, payload = _post(port, "/v1.47/containers/create?name=syn-sidecar-1", sidecar_body())
    assert status == 201 and payload["Id"] == "abc"
    assert daemon.creates == [("/v1.47/containers/create?name=syn-sidecar-1", json.dumps(sidecar_body()).encode())]


@pytest.mark.parametrize(
    "host_config",
    [{"Privileged": True}, {"Binds": ["/:/host"]}, {"NetworkMode": "host"}, {"Binds": ["/var/run/docker.sock:/s"]}],
)
def test_refused_create_never_reaches_the_daemon(guard: tuple[int, _FakeDaemon], host_config: dict[str, object]) -> None:
    port, daemon = guard
    body = workspace_body()
    hc = body["HostConfig"]
    assert isinstance(hc, dict)
    hc.update(host_config)
    status, payload = _post(port, "/v1.47/containers/create", body)
    assert status == 403
    assert str(payload["message"]).startswith("refused by the Syntropic137 container-create guard")
    assert daemon.creates == []


def test_only_create_is_served(guard: tuple[int, _FakeDaemon]) -> None:
    port, daemon = guard
    status, _ = _post(port, "/v1.47/containers/abc/start", {})
    assert status == 403 and daemon.creates == []
