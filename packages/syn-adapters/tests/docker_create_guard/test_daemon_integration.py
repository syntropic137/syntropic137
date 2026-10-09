"""The container-create guard against a real Docker daemon (#1806).

Runs the guard in-process on the host's Docker socket and POSTs create bodies
to it: the platform's workspace and sidecar shapes must produce a container,
the host-access shapes must produce none. Skipped when no daemon is reachable.
Not run in agent workspaces (no Docker); CI / the orchestrator runs it.
"""

from __future__ import annotations

import http.client
import json
import os
import threading
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

from syn_adapters.docker_create_guard.policy import DEFAULT_IMAGE_PREFIXES, CreatePolicy, JsonObject
from syn_adapters.docker_create_guard.server import DockerSocket, GuardHost, make_handler

SOCKET = os.environ.get("SYN_DOCKER_CREATE_GUARD_SOCKET", "/var/run/docker.sock")
IMAGE = "alpine:3.20"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not Path(SOCKET).exists(), reason=f"no Docker socket at {SOCKET}"),
]


@pytest.fixture
def guard(tmp_path: Path) -> Iterator[tuple[int, DockerSocket, Path]]:
    daemon = DockerSocket(SOCKET)
    status, _, _ = daemon.request("POST", f"/images/create?fromImage={IMAGE}", b"", {})
    assert status == 200, f"could not pull {IMAGE}"
    policy = CreatePolicy(
        workspace_root=str(tmp_path), image_prefixes=(*DEFAULT_IMAGE_PREFIXES, "alpine")
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(policy, GuardHost(daemon, str(tmp_path), str(tmp_path)))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], daemon, tmp_path
    server.shutdown()


def _create(port: int, name: str, host_config: JsonObject, *, top_level: bool = False) -> int:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    body: JsonObject = {"Image": IMAGE, "Cmd": ["true"]}
    if top_level:
        body.update(host_config)
    else:
        body["HostConfig"] = host_config
    conn.request(
        "POST",
        f"/containers/create?name={name}",
        body=json.dumps(body),
        headers={"Content-Type": "application/json"},
    )
    return conn.getresponse().status


def _exists(daemon: DockerSocket, name: str) -> bool:
    status, _, _ = daemon.request("GET", f"/containers/{name}/json", None, {})
    return status == 200


def _remove(daemon: DockerSocket, name: str) -> None:
    daemon.request("DELETE", f"/containers/{name}?force=1", None, {})


def test_workspace_shape_is_created(guard: tuple[int, DockerSocket, Path]) -> None:
    port, daemon, root = guard
    (root / "ws-1").mkdir()
    name = f"syn-guard-it-{uuid.uuid4().hex[:8]}"
    try:
        status = _create(
            port,
            name,
            {
                "Binds": [f"{root}/ws-1:/workspace:rw"],
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges"],
                "ReadonlyRootfs": True,
                "Tmpfs": {"/tmp": "rw,size=16m"},
                "NetworkMode": "none",
            },
        )
        assert status == 201 and _exists(daemon, name)
    finally:
        _remove(daemon, name)


def test_sidecar_shape_is_created(guard: tuple[int, DockerSocket, Path]) -> None:
    port, daemon, _ = guard
    name = f"syn-guard-it-{uuid.uuid4().hex[:8]}"
    try:
        assert (
            _create(
                port, name, {"NetworkMode": "bridge", "Memory": 134217728, "NanoCpus": 250000000}
            )
            == 201
        )
        assert _exists(daemon, name)
    finally:
        _remove(daemon, name)


def test_symlink_out_of_the_root_is_refused(guard: tuple[int, DockerSocket, Path]) -> None:
    port, daemon, root = guard
    (root / "escape").symlink_to("/")
    name = f"syn-guard-it-{uuid.uuid4().hex[:8]}"
    try:
        assert _create(port, name, {"Binds": [f"{root}/escape:/host"]}) == 403
        assert not _exists(daemon, name)
    finally:
        _remove(daemon, name)


@pytest.mark.parametrize(
    "host_config",
    [
        {"Privileged": True},
        {"Binds": ["/:/host"]},
        {"NetworkMode": "host"},
        {"Binds": [f"{SOCKET}:/var/run/docker.sock"]},
        {"PidMode": "container:syn137-docker-create-guard"},
        {"MaskedPaths": [], "ReadonlyPaths": []},
        {"SecurityOpt": ['seccomp={"defaultAction":"SCMP_ACT_ALLOW"}']},
    ],
    ids=[
        "privileged",
        "bind-root",
        "host-network",
        "docker-sock",
        "join-guard-pid",
        "unmasked-proc",
        "allow-all-seccomp",
    ],
)
def test_host_access_is_refused_and_nothing_is_created(
    guard: tuple[int, DockerSocket, Path], host_config: JsonObject
) -> None:
    port, daemon, _ = guard
    name = f"syn-guard-it-{uuid.uuid4().hex[:8]}"
    try:
        assert _create(port, name, host_config) == 403
        assert not _exists(daemon, name)
    finally:
        _remove(daemon, name)


@pytest.mark.parametrize(
    "fields",
    [{"Privileged": True}, {"Binds": ["/:/host"]}],
    ids=["privileged", "bind-root"],
)
def test_deprecated_top_level_host_config_is_refused(
    guard: tuple[int, DockerSocket, Path], fields: JsonObject
) -> None:
    port, daemon, _ = guard
    name = f"syn-guard-it-{uuid.uuid4().hex[:8]}"
    try:
        assert _create(port, name, fields, top_level=True) == 403
        assert not _exists(daemon, name)
    finally:
        _remove(daemon, name)
