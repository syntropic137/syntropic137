"""A phase's ``resources.pids_limit`` reaches agentic-workspace's ``--pids-limit`` (okrs-51p.30).

The workspace's process limit was agentic-workspace's hardcoded
``SecurityConfig.pids_limit=256``, and threads count against it: cargo,
libtest, ``node --test`` and lavapipe suites fork-fail with EAGAIN under it.
syn137 now owns the default (``SYN_WORKSPACE_PIDS_LIMIT``) and a phase may
raise it. The limit travels ``WorkspaceService`` -> ``SecurityPolicy`` ->
``AgenticIsolationAdapter.create`` -> ``WorkspaceConfig.security``, the
per-workspace override the Docker provider prefers to its own policy. These
tests start at the service config and end at the ``WorkspaceConfig`` the
provider is handed and the argv the real provider would render from it.

The override is a ``dataclasses.replace`` of the adapter's policy, so the
image-derived hardening (runtime, AppArmor, seccomp) must survive it.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentic_isolation import SecurityConfig, WorkspaceConfig
from agentic_isolation.providers.base import ExecuteResult
from agentic_isolation.providers.docker import WorkspaceDockerProvider

from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter
from syn_adapters.workspace_backends.service.workspace_lifecycle import build_isolation_config
from syn_adapters.workspace_backends.service.workspace_service import WorkspaceServiceConfig

pytestmark = pytest.mark.unit

#: A policy no default produces, so a replace that rebuilt it from defaults
#: instead of copying it would be caught.
_PINNED = dataclasses.replace(
    SecurityConfig.production(), apparmor_profile="syn-test-profile", tmpfs_home=False
)


async def _workspace_config(pids_limit: int | None) -> WorkspaceConfig:
    """Create through the adapter against a double provider; return what it was handed."""
    isolation_config = build_isolation_config(
        config=WorkspaceServiceConfig(pids_limit=256, pids_max=4096),
        workspace_id="ws-1",
        execution_id="exec-1",
        workflow_id="wf-1",
        phase_id="build",
        extra_environment=None,
        pids_limit=pids_limit,
    )
    workspace = MagicMock()
    workspace.id = "ws-1"
    workspace.metadata = {"workspace_dir": "/tmp/ws-1"}
    provider = MagicMock()
    provider.create = AsyncMock(return_value=workspace)
    provider.execute = AsyncMock(return_value=ExecuteResult(exit_code=0, stdout="", stderr=""))

    adapter = AgenticIsolationAdapter(security=_PINNED)

    async def _passthrough(image_ref: str) -> str:
        return image_ref

    with (
        patch.object(adapter, "_provider", provider),
        patch(
            "syn_adapters.workspace_backends.backend_kit.verify_image_async",
            side_effect=_passthrough,
        ),
    ):
        await adapter.create(isolation_config)

    return provider.create.call_args.args[0]


def _argv(ws_config: WorkspaceConfig) -> list[str]:
    return WorkspaceDockerProvider()._build_run_command(
        container_name="c-1",
        workspace_id="ws-1",
        workspace_dir=Path("/tmp/ws-1"),
        image=ws_config.image,
        config=ws_config,
        security=ws_config.security,
    )


@pytest.mark.asyncio
async def test_a_phase_pids_request_is_the_workspace_pids_limit() -> None:
    ws_config = await _workspace_config(2048)

    assert ws_config.security.pids_limit == 2048
    assert "--pids-limit=2048" in _argv(ws_config)


@pytest.mark.asyncio
async def test_no_request_is_the_default_of_256_as_before() -> None:
    ws_config = await _workspace_config(None)

    assert ws_config.security.pids_limit == 256
    assert "--pids-limit=256" in _argv(ws_config)


@pytest.mark.asyncio
async def test_the_override_keeps_every_other_security_field() -> None:
    ws_config = await _workspace_config(2048)

    assert ws_config.security == dataclasses.replace(_PINNED, pids_limit=2048)
    assert _PINNED.pids_limit == 256, "the adapter's own policy must not be mutated"
