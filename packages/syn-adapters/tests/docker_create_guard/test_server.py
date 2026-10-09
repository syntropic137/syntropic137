"""The guard's HTTP front: a refused create never reaches the daemon, an allowed one is replayed."""

from __future__ import annotations

import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

from syn_adapters.docker_create_guard.policy import CreatePolicy, JsonObject
from syn_adapters.docker_create_guard.server import DockerSocket, GuardHost, make_handler

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
        return (
            201,
            [("Content-Type", "application/json"), ("Api-Version", "1.47")],
            b'{"Id":"abc","Warnings":[]}',
        )


@pytest.fixture
def guard() -> Iterator[tuple[int, _FakeDaemon]]:
    daemon = _FakeDaemon()
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        make_handler(CreatePolicy(workspace_root=ROOT), GuardHost(daemon, ROOT, None)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], daemon
    server.shutdown()


def _post(port: int, path: str, body: object) -> tuple[int, JsonObject]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", path, body=json.dumps(body), headers={"Content-Type": "application/json"})
    response = conn.getresponse()
    return response.status, json.loads(response.read())


def test_allowed_create_is_replayed_with_its_query(guard: tuple[int, _FakeDaemon]) -> None:
    port, daemon = guard
    status, payload = _post(port, "/v1.47/containers/create?name=syn-sidecar-1", sidecar_body())
    assert status == 201 and payload["Id"] == "abc"
    assert daemon.creates == [
        ("/v1.47/containers/create?name=syn-sidecar-1", json.dumps(sidecar_body()).encode())
    ]


@pytest.mark.parametrize(
    "host_config",
    [
        {"Privileged": True},
        {"Binds": ["/:/host"]},
        {"NetworkMode": "host"},
        {"Binds": ["/var/run/docker.sock:/s"]},
    ],
)
def test_refused_create_never_reaches_the_daemon(
    guard: tuple[int, _FakeDaemon], host_config: JsonObject
) -> None:
    port, daemon = guard
    body = workspace_body()
    hc = body["HostConfig"]
    assert isinstance(hc, dict)
    hc.update(host_config)
    status, payload = _post(port, "/v1.47/containers/create", body)
    assert status == 403
    assert str(payload["message"]).startswith("refused by the Syntropic137 container-create guard")
    assert daemon.creates == []


@pytest.mark.parametrize("path", ["/v1.47/containers/abc/start", "/v1.47/swarm/init"])
def test_only_create_is_served(guard: tuple[int, _FakeDaemon], path: str) -> None:
    # A body the policy allows, so only the path check can refuse it.
    port, daemon = guard
    status, payload = _post(port, path, sidecar_body())
    assert status == 403 and "only serves container create" in str(payload["message"])
    assert daemon.creates == []


class TestGuardHostResolvesThroughTheMount:
    def test_paths_translate_and_symlinks_resolve(self, tmp_path: Path) -> None:
        (tmp_path / "ws-1").mkdir()
        (tmp_path / "escape").symlink_to("/")
        host = GuardHost(DockerSocket("/nonexistent"), "/srv/ws", str(tmp_path))
        assert host.real_path("/srv/ws/ws-1") == "/srv/ws/ws-1"
        assert host.real_path("/srv/ws/escape") == "/"
        assert host.real_path("/srv/ws/missing") is None
        assert host.real_path("/elsewhere") is None

    def test_unmounted_root_sees_nothing(self) -> None:
        host = GuardHost(DockerSocket("/nonexistent"), "/srv/ws", None)
        assert host.real_path("/srv/ws/ws-1") is None
