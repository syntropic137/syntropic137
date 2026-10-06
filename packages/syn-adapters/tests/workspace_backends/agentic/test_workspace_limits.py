"""Configured workspace limits reach `docker run` (#1606).

The limit used to be computed onto `IsolationConfig.security_policy` and then
dropped at `AgenticIsolationAdapter.create`, which built `WorkspaceConfig`
without `limits=`. Every object on either side of that hop looked right, so
these tests start at the operator's env var and end at the argv the real
`DockerProvider` would execute.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentic_isolation import SecurityConfig, WorkspaceConfig
from agentic_isolation.providers.docker import WorkspaceDockerProvider

from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter
from syn_adapters.workspace_backends.service.workspace_lifecycle import build_isolation_config
from syn_adapters.workspace_backends.service.workspace_service import WorkspaceServiceConfig
from syn_shared.settings.workspace import WorkspaceSettings

pytestmark = pytest.mark.unit


async def _docker_run_argv(phase_id: str | None) -> list[str]:
    """Provision through the adapter and render what Docker would be asked to run."""
    with patch.dict(
        os.environ,
        {"SYN_WORKSPACE_MEMORY_LIMIT_MB": "1536", "SYN_WORKSPACE_CPU_LIMIT": "1.5"},
        clear=True,
    ):
        settings = WorkspaceSettings(_env_file=None)  # type: ignore[call-arg]

    isolation_config = build_isolation_config(
        config=WorkspaceServiceConfig.from_settings(settings),
        workspace_id="ws-1",
        execution_id="exec-1",
        workflow_id="wf-1",
        phase_id=phase_id,
        extra_environment=None,
    )

    workspace = MagicMock()
    workspace.id = "ws-1"
    workspace.metadata = {"workspace_dir": "/tmp/ws-1"}
    provider = MagicMock()
    provider.create = AsyncMock(return_value=workspace)

    adapter = AgenticIsolationAdapter()

    async def _passthrough(image_ref: str) -> str:
        return image_ref

    with (
        patch.object(adapter, "_provider", provider),
        patch(
            "syn_adapters.workspace_backends.agentic.adapter.verify_image_async",
            side_effect=_passthrough,
        ),
    ):
        await adapter.create(isolation_config)

    ws_config: WorkspaceConfig = provider.create.call_args.args[0]
    return WorkspaceDockerProvider()._build_run_command(
        container_name="c-1",
        workspace_id="ws-1",
        workspace_dir=Path("/tmp/ws-1"),
        image=ws_config.image,
        config=ws_config,
        security=SecurityConfig.production(),
    )


@pytest.mark.asyncio
async def test_configured_limits_reach_docker_run() -> None:
    argv = await _docker_run_argv(phase_id="phase-7")

    assert "--memory=1536m" in argv
    assert "--cpus=1.5" in argv


@pytest.mark.asyncio
async def test_container_is_labelled_with_its_phase() -> None:
    argv = await _docker_run_argv(phase_id="phase-7")

    assert "--label=syn.phase_id=phase-7" in argv
    assert "--label=syn.execution_id=exec-1" in argv
    assert "--label=syn.workspace_id=ws-1" in argv


@pytest.mark.asyncio
async def test_workspace_without_a_phase_has_no_phase_label() -> None:
    argv = await _docker_run_argv(phase_id=None)

    assert not [arg for arg in argv if arg.startswith("--label=syn.phase_id")]
