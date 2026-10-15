"""Docker-backed evidence that the recorded runtime is the one Docker enforces.

Real ``WorkspaceDockerProvider``, real container. Run with:

    SYN_CONTRACT_TEST_IMAGE=busybox:1.36 \
      uv run pytest -m integration packages/syn-adapters/tests/test_docker_workspace_runtime.py

The unit tests prove the setting reaches ``SecurityConfig.runtime`` and that
``Workspace.metadata`` is read back. This proves the last hop neither can see:
what syn records from that metadata is the runtime ``docker inspect`` reports
for the container.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import TYPE_CHECKING

import pytest
from agentic_isolation import SecurityConfig, WorkspaceConfig, WorkspaceDockerProvider

from syn_adapters.workspace_backends.agentic.runtime_mapping import (
    isolation_runtime_from_metadata,
    resolve_host_runtime,
    to_aw_runtime,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationRuntime,
)
from syn_shared.settings.workspace import WorkspaceRuntime

if TYPE_CHECKING:
    from pathlib import Path

IMAGE = os.environ.get("SYN_CONTRACT_TEST_IMAGE")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not IMAGE, reason="Set SYN_CONTRACT_TEST_IMAGE to any image with sh"),
]


async def _recorded_and_enforced(
    tmp_path: Path, requested: WorkspaceRuntime | None
) -> tuple[IsolationRuntime | None, str, str]:
    """Create one container; return syn's record, its alias, and Docker's HostConfig.Runtime."""
    assert IMAGE is not None
    provider = WorkspaceDockerProvider(
        default_image=IMAGE,
        default_network="none",
        workspace_base_dir=tmp_path / "workspaces",
        security=SecurityConfig(runtime=to_aw_runtime(requested)),
    )
    workspace = await provider.create(WorkspaceConfig(provider="docker", image=IMAGE))
    try:
        inspected = json.loads(
            subprocess.run(
                ["docker", "inspect", workspace.metadata.get("container_id", workspace.id)],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )[0]
        return (
            isolation_runtime_from_metadata(workspace.metadata),
            workspace.metadata["runtime_alias"],
            inspected["HostConfig"]["Runtime"],
        )
    finally:
        await provider.teardown(target=workspace)


async def test_explicit_runc_is_recorded_and_enforced(tmp_path: Path) -> None:
    recorded, _, enforced = await _recorded_and_enforced(tmp_path, WorkspaceRuntime.RUNC)

    assert recorded == IsolationRuntime(
        requested=WorkspaceRuntime.RUNC, effective=WorkspaceRuntime.RUNC
    )
    assert enforced == "runc"


async def test_auto_records_the_runtime_docker_ran(tmp_path: Path) -> None:
    """Auto on any host: the record is AW's resolution, and Docker enforced it.

    The expected runtime is asked of agentic-workspace's resolver for this
    host, never inferred from the alias name, so a record that disagrees with
    the resolver fails even when the alias matches.
    """
    expected = resolve_host_runtime(None)
    recorded, alias, enforced = await _recorded_and_enforced(tmp_path, None)

    assert expected.error is None
    assert recorded == IsolationRuntime(requested=None, effective=expected.effective)
    assert alias == expected.alias
    assert enforced == alias
