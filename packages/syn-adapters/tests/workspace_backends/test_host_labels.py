"""Workspace and sidecar containers say which API host created them (#1310 0.4).

Each test drives the code that hands labels to Docker - the agentic adapter's
`create()` and, for the sidecar, `provision_workspace()` through the real
`DockerSidecarAdapter` - and reads what reached the boundary, so a label built
correctly and dropped one hop later fails here.
"""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentic_isolation.providers.base import ExecuteResult

from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter
from syn_adapters.workspace_backends.docker.docker_sidecar_adapter import DockerSidecarAdapter
from syn_adapters.workspace_backends.host_labels import UNKNOWN_GENERATION
from syn_adapters.workspace_backends.service.workspace_lifecycle import provision_workspace
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationConfig,
    IsolationHandle,
)
from syn_shared.env_constants import ENV_BUILD_IMAGE_TAG
from syn_shared.settings import reset_settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator

pytestmark = pytest.mark.unit

HOST_ID = "beta-host-7"
IMAGE_TAG = "v0.31.0-beta.17"


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    """`SYN_HOST_ID` is read through the cached Settings; never leak one."""
    reset_settings()
    yield
    reset_settings()


@pytest.fixture
def stamped_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYN_HOST_ID", HOST_ID)
    monkeypatch.setenv(ENV_BUILD_IMAGE_TAG, IMAGE_TAG)


@pytest.fixture
def unstamped_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """A compose build: no host id configured, image tag stamped empty."""
    monkeypatch.delenv("SYN_HOST_ID", raising=False)
    monkeypatch.setenv(ENV_BUILD_IMAGE_TAG, "")


def _isolation_config() -> IsolationConfig:
    return IsolationConfig(
        execution_id="exec-abc",
        workspace_id="ws-xyz",
        workflow_id="wf-1",
        phase_id="phase-1",
        image="test:latest",
    )


async def _passthrough_verify(image_ref: str) -> str:
    return image_ref


async def _workspace_labels() -> dict[str, str]:
    """Provision through the real adapter; return the labels the provider got."""
    workspace = MagicMock()
    workspace.id = "ws-123"
    workspace.metadata = {"workspace_dir": "/tmp/x"}
    provider = MagicMock()
    provider.create = AsyncMock(return_value=workspace)
    provider.execute = AsyncMock(return_value=ExecuteResult(exit_code=0, stdout="", stderr=""))
    adapter = AgenticIsolationAdapter()
    with (
        patch.object(adapter, "_provider", provider),
        patch(
            "syn_adapters.workspace_backends.agentic.adapter.verify_image_async",
            side_effect=_passthrough_verify,
        ),
    ):
        await adapter.create(_isolation_config())
    return dict(provider.create.await_args.args[0].labels)


async def _sidecar_labels() -> dict[str, str]:
    """Provision a workspace with a sidecar; return the sidecar's `--label`s.

    Goes through `provision_workspace`, the only producer of `SidecarConfig`,
    so the execution id has to survive that hop to reach the command.
    """
    service = MagicMock()
    service._isolation.create = AsyncMock(
        return_value=IsolationHandle(isolation_id="iso-1", isolation_type="docker")
    )
    service._sidecar = DockerSidecarAdapter()
    service._config.allowed_hosts = ("api.github.com",)
    run = AsyncMock(return_value="sidecar-container-id")
    module = "syn_adapters.workspace_backends.docker.docker_sidecar_adapter"
    with (
        patch(
            "syn_adapters.workspace_backends.service.workspace_lifecycle._read_image_manifest",
            AsyncMock(return_value=None),
        ),
        patch(f"{module}.get_container_network", AsyncMock(return_value="agent-net")),
        patch(f"{module}.run_sidecar_container", run),
        patch(f"{module}.wait_for_healthy", AsyncMock()),
    ):
        await provision_workspace(
            service, _isolation_config(), MagicMock(), "ws-xyz", with_sidecar=True
        )
    docker_cmd: list[str] = run.await_args.args[0]
    flags = [arg.removeprefix("--label=") for arg in docker_cmd if arg.startswith("--label=")]
    return dict(flag.split("=", 1) for flag in flags)


async def test_workspace_container_carries_every_label(stamped_host: None) -> None:
    assert await _workspace_labels() == {
        "syn.execution_id": "exec-abc",
        "syn.workspace_id": "ws-xyz",
        "syn.phase_id": "phase-1",
        "syn.host_id": HOST_ID,
        "syn.host_generation": IMAGE_TAG,
    }


async def test_sidecar_container_carries_every_label(stamped_host: None) -> None:
    assert await _sidecar_labels() == {
        "syn.workspace_id": "ws-xyz",
        "syn.execution_id": "exec-abc",
        "syn.component": "sidecar",
        "syn.host_id": HOST_ID,
        "syn.host_generation": IMAGE_TAG,
    }


@pytest.mark.parametrize("labels_of", [_workspace_labels, _sidecar_labels])
async def test_an_unconfigured_host_is_named_by_its_hostname(
    unstamped_host: None, labels_of: Callable[[], Awaitable[dict[str, str]]]
) -> None:
    """No `SYN_HOST_ID` falls back to the hostname; an empty tag is `unknown`.

    Both labels are still written, so a later reap can filter on their presence.
    """
    labels = await labels_of()
    assert labels["syn.host_id"] == socket.gethostname()
    assert labels["syn.host_generation"] == UNKNOWN_GENERATION
