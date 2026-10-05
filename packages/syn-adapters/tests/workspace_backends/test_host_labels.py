"""Workspace and sidecar containers name the host that created them (#1310, 0.4).

Both builders are asserted on what reaches Docker - the provider's
``WorkspaceConfig.labels`` and the sidecar's ``docker run`` argv - and the
sidecar's execution id is followed from ``provision_workspace``, the hop that
had no execution id to give before this change. The fixture values cannot be
the defaults: the host id is not this machine's hostname and the generation is
not empty.
"""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.workspace_backends.docker.docker_sidecar_helpers import (
    build_sidecar_docker_cmd,
)
from syn_adapters.workspace_backends.host_labels import host_labels
from syn_adapters.workspace_backends.service.workspace_lifecycle import provision_workspace
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationConfig,
    IsolationHandle,
    SidecarConfig,
)
from syn_shared.settings import reset_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

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
def test_sidecar_docker_run_carries_every_label() -> None:
    config = SidecarConfig(workspace_id="ws-xyz", execution_id="exec-abc")
    argv = build_sidecar_docker_cmd(
        config,
        "syn-sidecar-test",
        "agent-net",
        "http://tokens:8080",
        "sidecar:latest",
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
    argv = build_sidecar_docker_cmd(sidecar_config, "n", "net", "http://t", "img")
    assert _labels_from_argv(argv)["syn.execution_id"] == "exec-from-isolation"


def test_host_id_defaults_to_the_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SYN_HOST_ID", raising=False)
    monkeypatch.delenv("SYN_BUILD_IMAGE_TAG", raising=False)
    reset_settings()
    try:
        assert host_labels() == {
            "syn.host_id": socket.gethostname(),
            "syn.host_generation": "",
        }
    finally:
        reset_settings()


def test_empty_host_id_falls_back_to_the_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYN_HOST_ID", "")
    reset_settings()
    try:
        assert host_labels()["syn.host_id"] == socket.gethostname()
    finally:
        reset_settings()
