"""V7 and V7b on real Docker (#1310 1.5, ADR-072 D5, D6).

V7: host A dies while host B holds another run. Reaping A's fenced run removes
A's workspace and legacy sidecar for that run and nothing of B's.
V7b: an unlabelled container is left, with a WARN, while another executor is
live, and reaped only when none is.

Labels come from the real producers (the agentic adapter's ``_container_labels``
and ``build_sidecar_docker_cmd``), so a producer that drops a label fails here.
The containers are plain ``alpine`` stand-ins carrying exactly those labels.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.workspace_backends.agentic.adapter import _container_labels
from syn_adapters.workspace_backends.docker.docker_sidecar_helpers import (
    build_sidecar_docker_cmd,
)
from syn_adapters.workspace_backends.host_labels import _process_suffix
from syn_api.services import unlabelled_containers
from syn_api.services.dead_host_reaper import DockerDeadHostReaper
from syn_api.services.unlabelled_containers import reap_unlabelled_if_alone
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationConfig,
    SidecarConfig,
)
from syn_domain.contexts.orchestration.ports import FencedRun
from syn_shared.settings import reset_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("docker") is None, reason="requires Docker"),
]

IMAGE = os.environ.get("SYN_SPOOL_RELEASE_TEST_IMAGE", "alpine:3")


async def _docker(*args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode().strip()


async def _exists(name: str) -> bool:
    code, _ = await _docker("container", "inspect", name)
    return code == 0


def _labels_as(
    host: str, execution_id: str, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, str], dict[str, str]]:
    """(workspace, sidecar) labels as process ``host`` would stamp them."""
    monkeypatch.setenv("SYN_HOST_ID", host)
    monkeypatch.setenv("SYN_EXECUTION_RUN_QUEUE_ENABLED", "true")
    reset_settings()
    _process_suffix.cache_clear()
    workspace = _container_labels(
        IsolationConfig(
            execution_id=execution_id,
            workspace_id=f"ws-{execution_id}",
            workflow_id="wf",
            phase_id="p1",
            image="unused",
        )
    )
    cmd = build_sidecar_docker_cmd(
        SidecarConfig(workspace_id=f"ws-{execution_id}", execution_id=execution_id),
        container_name="unused",
        network_name="unused",
        token_service_url="http://unused",
        default_image="unused",
    )
    sidecar = dict(
        arg.removeprefix("--label=").split("=", 1) for arg in cmd if arg.startswith("--label=")
    )
    return workspace, sidecar


class _Containers:
    def __init__(self) -> None:
        self.names: list[str] = []

    async def run(self, name: str, labels: dict[str, str]) -> None:
        label_args = [f"--label={k}={v}" for k, v in labels.items()]
        code, _ = await _docker("run", "-d", "--name", name, *label_args, IMAGE, "sleep", "300")
        assert code == 0, f"could not start {name}"
        self.names.append(name)


@pytest.fixture
async def containers() -> AsyncIterator[_Containers]:
    code, _ = await _docker("image", "inspect", IMAGE)
    if code != 0:
        pytest.skip(f"{IMAGE} is not available locally")
    made = _Containers()
    try:
        yield made
    finally:
        if made.names:
            await _docker("rm", "-f", *made.names)
        reset_settings()
        _process_suffix.cache_clear()


async def test_v7_reaping_a_dead_hosts_run_removes_only_its_workspace_and_sidecar(
    containers: _Containers, monkeypatch: pytest.MonkeyPatch
) -> None:
    tag = uuid4().hex[:8]
    a_ws, a_sidecar = _labels_as(f"host-a-{tag}", "exec-a", monkeypatch)
    dead_host = a_ws["syn.host_id"]
    assert a_sidecar["syn.host_id"] == dead_host  # one process, one id on every container
    _, a_other_sidecar = _labels_as(dead_host.rsplit(".", 1)[0], "exec-a2", monkeypatch)
    b_ws, b_sidecar = _labels_as(f"host-b-{tag}", "exec-b", monkeypatch)

    await containers.run(f"agentic-ws-a-{tag}", a_ws)
    await containers.run(f"syn-sidecar-a-{tag}", a_sidecar)
    await containers.run(f"agentic-ws-b-{tag}", b_ws)
    await containers.run(f"syn-sidecar-b-{tag}", b_sidecar)
    await containers.run(f"syn-sidecar-a2-{tag}", a_other_sidecar)

    fenced = FencedRun(
        execution_id="exec-a", executor_id=dead_host, reconciler=b_ws["syn.host_id"], token=2
    )
    assert await DockerDeadHostReaper().reap(fenced.executor_id, fenced.execution_id)

    assert not await _exists(f"agentic-ws-a-{tag}")
    assert not await _exists(f"syn-sidecar-a-{tag}")
    assert await _exists(f"agentic-ws-b-{tag}")  # B's workspace survives
    assert await _exists(f"syn-sidecar-b-{tag}")  # and its legacy sidecar
    # A different process (a new id) is not the dead host, even on the same machine.
    assert await _exists(f"syn-sidecar-a2-{tag}")


class _Liveness:
    def __init__(self, others: bool) -> None:
        self.others = others

    async def others_live(self, host_id: str) -> bool:
        return self.others


async def test_v7b_an_unlabelled_container_is_left_and_warned_while_another_host_is_live(
    containers: _Containers, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = f"agentic-ws-unlabelled-{uuid4().hex[:8]}"
    # Narrowed to this test's container: the real selectors would also reap a
    # developer's own unlabelled containers on the machine running the test.
    monkeypatch.setattr(unlabelled_containers, "_SELECTORS", (f"name={name}",))
    await containers.run(name, {})
    caplog.set_level(logging.WARNING)

    await reap_unlabelled_if_alone(_Liveness(others=True), "me")  # type: ignore[arg-type]
    assert await _exists(name)
    assert any(
        "unlabelled" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records
    )

    await reap_unlabelled_if_alone(_Liveness(others=False), "me")  # type: ignore[arg-type]
    assert not await _exists(name)
