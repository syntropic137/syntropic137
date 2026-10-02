"""Kill the producing container, then recover its native files through real Docker."""

from __future__ import annotations

import json
import os
import shlex
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from agentic_isolation import MountConfig, SecurityConfig, WorkspaceConfig, WorkspaceDockerProvider

from syn_adapters.session_inventory.docker_recovery import DockerSpoolRecovery, _docker
from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
from syn_adapters.session_inventory.native_evidence import AgenticNativeSessionEvidence
from syn_adapters.session_inventory.postgres_spools import PostgresCaptureSpools
from syn_adapters.session_inventory.recovery_worker import CaptureRecoveryWorker
from syn_adapters.session_inventory.spool_drain import LocalSpoolDrain
from syn_adapters.session_inventory.workspace_location import workspace_capture_location
from syn_domain.contexts.agent_sessions import (
    CaptureLocalTranscriptHandler,
    CaptureSpool,
    RunIdentity,
)

if TYPE_CHECKING:
    from pathlib import Path

    import asyncpg

IMAGE = os.environ.get("SYN_CAPTURE_TEST_IMAGE")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not IMAGE, reason="Set SYN_CAPTURE_TEST_IMAGE to a workspace image with local capture"
    ),
]


async def test_missing_volume_is_not_replaced_by_empty_capture() -> None:
    assert IMAGE is not None
    spool = CaptureSpool(
        run=RunIdentity(source_instance_id=str(uuid4()), execution_id="missing-run"),
        session_id="session",
        phase_id="phase",
    )
    location = workspace_capture_location(spool.run, spool.session_id)
    with pytest.raises(FileNotFoundError, match="not available"):
        async with DockerSpoolRecovery(IMAGE).open(spool):
            pytest.fail("Missing capture storage must not yield a reader")
    inspected = await _docker(["volume", "inspect", location.volume_name])
    assert inspected.exit_code != 0


async def test_killed_workspace_recovers_native_bytes_without_remote_store(
    db_pool: asyncpg.Pool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert IMAGE is not None
    monkeypatch.setenv("SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES", "true")
    run = RunIdentity(source_instance_id=str(uuid4()), execution_id="run")
    spool = CaptureSpool(run=run, session_id="session", phase_id="phase")
    location = workspace_capture_location(run, spool.session_id)
    journal = PostgresSessionEvidence(db_pool)
    await journal.ensure_ready()
    registry = PostgresCaptureSpools(db_pool, run.source_instance_id)
    await registry.project(spool)
    provider = WorkspaceDockerProvider(
        default_network="none",
        workspace_base_dir=tmp_path / "workspaces",
        security=SecurityConfig(use_gvisor=False),
    )
    workspace = None
    try:
        workspace = await provider.create(
            WorkspaceConfig(
                image=IMAGE,
                mounts=[MountConfig(location.volume_name, "/spool", kind="volume")],
                environment={
                    "AGENTIC_CAPABILITIES": "session-store",
                    "AGENTIC_SESSION_STORE_PROVIDER": "local",
                    "AGENTIC_SESSION_STORE_PARTITION": location.partition,
                },
            )
        )
        marker = f"/spool/.agentic-session-store/{location.partition}/.init-complete"
        ready = await provider.execute(
            workspace,
            f"for i in $(seq 1 100); do test -f {marker} && break; sleep 0.1; done; test -f {marker}",
            timeout=20,
        )
        assert ready.exit_code == 0, ready.stderr
        raw = '{"type":"user","sessionId":"native","timestamp":"2026-07-01T00:00:00Z","message":{"role":"user","content":"recover after kill"}}\r\n'
        written = await provider.execute(
            workspace,
            "mkdir -p ~/.claude/projects/project && printf %s "
            + shlex.quote(raw)
            + " > ~/.claude/projects/project/native.jsonl && sync",
        )
        assert written.exit_code == 0, written.stderr
        killed = await _docker(["kill", workspace.metadata["container_name"]])
        assert killed.exit_code == 0
        await provider.destroy(workspace)
        workspace = None
        archive = LocalSessionTranscriptArchive(tmp_path / "archive")
        await archive.ensure_ready()
        drain = LocalSpoolDrain(
            CaptureLocalTranscriptHandler(archive, journal, AgenticNativeSessionEvidence())
        )
        worker = CaptureRecoveryWorker(
            registry, DockerSpoolRecovery(IMAGE), drain, lease_seconds=120, retry_seconds=0
        )
        assert await worker.step()
        assert await journal.watermark(run) == 1
        bodies = [
            path.read_bytes() for path in (tmp_path / "archive").iterdir() if path.stat().st_size
        ]
        assert len(bodies) == 1
        assert json.loads(bodies[0])["raw"] == raw
        # A new helper hostname must not create a duplicate envelope revision.
        assert await worker.step()
        assert await journal.watermark(run) == 1
    finally:
        if workspace is not None:
            await provider.destroy(workspace)
        await _docker(["volume", "rm", location.volume_name])
