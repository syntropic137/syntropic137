"""Containers the API creates name the host that created them (#1310, 0.4).

The builders are asserted on what reaches Docker - the sidecar's and the
capture recovery helper's ``docker run`` argv - and the sidecar's execution id
is followed from ``provision_workspace``, the hop that had no execution id to
give before this change. The fixture values cannot be the defaults: the host id
is not this machine's engine ID and the generation is not empty.

The default host id is asked of a fake ``docker`` on PATH, so the real query
runs: an API recreated with a new hostname must get the same id from the same
daemon, and two daemons must get different ids.
"""

from __future__ import annotations

import socket
import stat
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.session_inventory import docker_recovery
from syn_adapters.workspace_backends import host_labels as host_labels_module
from syn_adapters.workspace_backends.docker.docker_sidecar_helpers import (
    build_sidecar_docker_cmd,
)
from syn_adapters.workspace_backends.host_labels import HostIdentityError, host_labels
from syn_adapters.workspace_backends.service.workspace_lifecycle import provision_workspace
from syn_domain.contexts.agent_sessions import CaptureSpool, RunIdentity
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationConfig,
    IsolationHandle,
    SidecarConfig,
)
from syn_shared.settings import reset_settings

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from agentic_isolation.providers.base import ExecuteResult

pytestmark = pytest.mark.unit

HOST_ID = "host-under-test-7f3a"
GENERATION = "v0.99.0-gen-c0ffee"


@pytest.fixture
def stamped_host(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SYN_HOST_ID", HOST_ID)
    monkeypatch.setenv("SYN_BUILD_IMAGE_TAG", GENERATION)
    reset_settings()
    yield
    reset_settings()


def _labels_from_argv(argv: list[str]) -> dict[str, str]:
    pairs = [a.removeprefix("--label=") for a in argv if a.startswith("--label=")]
    return dict(p.split("=", 1) for p in pairs)


@pytest.mark.usefixtures("stamped_host")
@pytest.mark.asyncio
async def test_sidecar_docker_run_carries_every_label() -> None:
    config = SidecarConfig(workspace_id="ws-xyz", execution_id="exec-abc")
    argv = build_sidecar_docker_cmd(
        config,
        "syn-sidecar-test",
        "agent-net",
        "http://tokens:8080",
        "sidecar:latest",
        await host_labels(),
    )

    assert _labels_from_argv(argv) == {
        "syn.execution_id": "exec-abc",
        "syn.workspace_id": "ws-xyz",
        "syn.component": "sidecar",
        "syn.host_id": HOST_ID,
        "syn.host_generation": GENERATION,
    }
    # Labels are options to `docker run`, so they must precede the image.
    assert argv[-1] == config.proxy_image


@pytest.mark.usefixtures("stamped_host")
@pytest.mark.asyncio
async def test_provisioning_hands_the_execution_id_to_the_sidecar() -> None:
    service = MagicMock()
    service._isolation.create = AsyncMock(
        return_value=IsolationHandle(isolation_id="c-1", isolation_type="docker")
    )
    service._sidecar.start = AsyncMock()
    service._config.allowed_hosts = ("api.github.com",)

    with patch(
        "syn_adapters.workspace_backends.service.workspace_lifecycle._read_image_manifest",
        AsyncMock(return_value=None),
    ):
        await provision_workspace(
            service,
            IsolationConfig(execution_id="exec-from-isolation", workspace_id="ws-xyz"),
            MagicMock(),
            "ws-xyz",
            with_sidecar=True,
        )

    sidecar_config = service._sidecar.start.await_args.args[0]
    argv = build_sidecar_docker_cmd(sidecar_config, "n", "net", "http://t", "img", {})
    assert _labels_from_argv(argv)["syn.execution_id"] == "exec-from-isolation"


@pytest.mark.usefixtures("stamped_host")
@pytest.mark.asyncio
async def test_capture_recovery_helper_docker_run_carries_host_labels() -> None:
    runs: list[list[str]] = []

    async def fake_docker(args: list[str], **_: object) -> ExecuteResult:
        from agentic_isolation.providers.base import ExecuteResult

        if args[0] == "run":
            runs.append(args)
            return ExecuteResult(exit_code=1, stdout="", stderr="", duration_ms=0)
        return ExecuteResult(exit_code=0, stdout="", stderr="", duration_ms=0)

    spool = CaptureSpool(
        run=RunIdentity(source_instance_id="src", execution_id="exec"),
        session_id="session",
        phase_id="phase",
    )
    with (
        patch.object(docker_recovery, "_docker", fake_docker),
        patch.object(docker_recovery, "verify_image_async", AsyncMock(return_value="img@sha")),
        pytest.raises(RuntimeError, match="Could not start capture recovery helper"),
    ):
        async with docker_recovery.DockerSpoolRecovery("img").open(spool):
            pytest.fail("A helper that did not start must not yield readers")

    [argv] = runs
    assert _labels_from_argv(argv) == {"syn.host_id": HOST_ID, "syn.host_generation": GENERATION}
    assert argv.index("img@sha") > max(i for i, a in enumerate(argv) if a.startswith("--label="))


@pytest.fixture
def fake_daemon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """A ``docker`` on PATH answering ``docker info`` with $FAKE_ENGINE_ID."""
    docker = tmp_path / "docker"
    docker.write_text(
        '#!/bin/sh\n[ "$1 $2 $3" = "info --format {{.ID}}" ] || exit 2\n'
        '[ -n "$FAKE_ENGINE_ID" ] || exit 1\necho "$FAKE_ENGINE_ID"\n'
    )
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    monkeypatch.delenv("SYN_HOST_ID", raising=False)
    yield monkeypatch
    reset_settings()


def _new_api_process(monkeypatch: pytest.MonkeyPatch, *, hostname: str) -> None:
    """What recreating the API container changes: its hostname, and every cache."""
    monkeypatch.setattr(socket, "gethostname", lambda: hostname)
    monkeypatch.setenv("HOSTNAME", hostname)
    monkeypatch.setattr(host_labels_module, "_engine_id", None)
    reset_settings()


@pytest.mark.asyncio
async def test_recreated_api_keeps_its_host_id(fake_daemon: pytest.MonkeyPatch) -> None:
    fake_daemon.setenv("FAKE_ENGINE_ID", "ENGINE-A:7F3A")
    _new_api_process(fake_daemon, hostname="3f2a1b0c9d8e")
    before = (await host_labels())["syn.host_id"]
    _new_api_process(fake_daemon, hostname="a9b8c7d6e5f4")
    after = (await host_labels())["syn.host_id"]

    assert before == after == "ENGINE-A:7F3A"


@pytest.mark.asyncio
async def test_two_daemons_get_two_host_ids(fake_daemon: pytest.MonkeyPatch) -> None:
    fake_daemon.setenv("FAKE_ENGINE_ID", "ENGINE-A:7F3A")
    _new_api_process(fake_daemon, hostname="same-name")
    first = (await host_labels())["syn.host_id"]
    fake_daemon.setenv("FAKE_ENGINE_ID", "ENGINE-B:0C1D")
    _new_api_process(fake_daemon, hostname="same-name")
    second = (await host_labels())["syn.host_id"]

    assert first != second


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [None, ""])
async def test_no_engine_id_and_no_setting_refuses_to_label(
    fake_daemon: pytest.MonkeyPatch, configured: str | None
) -> None:
    fake_daemon.delenv("FAKE_ENGINE_ID", raising=False)
    if configured is not None:
        fake_daemon.setenv("SYN_HOST_ID", configured)
    _new_api_process(fake_daemon, hostname="would-be-wrong")
    with pytest.raises(HostIdentityError, match="SYN_HOST_ID"):
        await host_labels()


@pytest.mark.asyncio
async def test_configured_host_id_wins_over_the_engine(fake_daemon: pytest.MonkeyPatch) -> None:
    fake_daemon.setenv("FAKE_ENGINE_ID", "ENGINE-A:7F3A")
    fake_daemon.setenv("SYN_HOST_ID", HOST_ID)
    _new_api_process(fake_daemon, hostname="ignored")
    assert (await host_labels())["syn.host_id"] == HOST_ID
