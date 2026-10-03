"""Real Docker: a capture volume in use by any container is never removed (#1398)."""

from __future__ import annotations

import os
import shutil
from uuid import uuid4

import pytest

from syn_adapters.session_inventory.docker_recovery import (
    DockerSpoolRecovery,
    _docker,
    volume_unreferenced,
)
from syn_adapters.session_inventory.workspace_location import workspace_capture_location
from syn_domain.contexts.agent_sessions import CaptureSpool, RunIdentity

IMAGE = os.environ.get("SYN_SPOOL_RELEASE_TEST_IMAGE", "alpine:3")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("docker") is None, reason="requires Docker"),
]


async def test_remove_refuses_attached_volume_then_removes_and_is_idempotent() -> None:
    spool = CaptureSpool(
        run=RunIdentity(source_instance_id=str(uuid4()), execution_id="run"),
        session_id="session",
        phase_id="phase",
    )
    volume = workspace_capture_location(spool.run, spool.session_id).volume_name
    image = await _docker(["image", "inspect", IMAGE], max_bytes=1 << 20)
    if image.exit_code != 0:
        pytest.skip(f"{IMAGE} is not available locally")
    assert (await _docker(["volume", "create", volume])).exit_code == 0
    assert await volume_unreferenced(volume)
    name = f"syn-spool-release-test-{uuid4().hex}"
    try:
        # A stopped container still references the volume, like a workspace
        # that has not been torn down: removal must wait for it.
        created = await _docker(["create", "--name", name, "-v", f"{volume}:/spool", IMAGE, "true"])
        assert created.exit_code == 0
        recovery = DockerSpoolRecovery(IMAGE)
        # Recovery opened now would not be exclusive, so it could not release.
        assert not await volume_unreferenced(volume)
        assert not await recovery.remove(spool)
        assert (await _docker(["volume", "inspect", volume])).exit_code == 0
        assert (await _docker(["rm", "-f", name])).exit_code == 0
        assert await volume_unreferenced(volume)
        assert await recovery.remove(spool)
        assert (await _docker(["volume", "inspect", volume])).exit_code != 0
        assert await recovery.remove(spool)  # already absent: idempotent
    finally:
        await _docker(["rm", "-f", name])
        await _docker(["volume", "rm", "-f", volume])
