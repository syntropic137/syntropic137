"""Docker-backed evidence that the recorded runtime is the one Docker enforces.

Real ``WorkspaceDockerProvider``, real container. Run with:

    uv run pytest -m integration packages/syn-adapters/tests/test_docker_workspace_runtime.py

The tests pull a digest-pinned busybox themselves, so a clean host with a
Docker daemon needs nothing else; ``SYN_CONTRACT_TEST_IMAGE`` overrides the
image with any other that has ``sh``. With no daemon, or an image that cannot
be pulled, they fail with the reason. They never skip: a skipped run is
indistinguishable from evidence nobody collected (PC-193).

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

# busybox:1.36.1, multi-arch index digest: the bytes cannot move under the tag.
_PINNED_IMAGE = "busybox@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662"
IMAGE = os.environ.get("SYN_CONTRACT_TEST_IMAGE") or _PINNED_IMAGE

pytestmark = pytest.mark.integration


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["docker", *args], capture_output=True, text=True, check=False)
    except FileNotFoundError as e:
        pytest.fail(f"docker CLI not found on PATH; these tests need a Docker host: {e}")


@pytest.fixture(scope="module", autouse=True)
def _image_present() -> None:
    """Provision IMAGE on this host, or fail saying why it could not."""
    info = _docker("info", "--format", "{{.ServerVersion}}")
    if info.returncode != 0:
        pytest.fail(f"Docker daemon unreachable (docker info): {info.stderr.strip()}")
    if _docker("image", "inspect", IMAGE).returncode == 0:
        return
    pull = _docker("pull", IMAGE)
    if pull.returncode != 0:
        pytest.fail(f"Could not pull {IMAGE}: {pull.stderr.strip()}")


async def _recorded_and_enforced(
    tmp_path: Path, requested: WorkspaceRuntime | None
) -> tuple[IsolationRuntime | None, str, str]:
    """Create one container; return syn's record, its alias, and Docker's HostConfig.Runtime."""
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
