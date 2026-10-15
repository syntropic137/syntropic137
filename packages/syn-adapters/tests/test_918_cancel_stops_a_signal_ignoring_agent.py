"""Real Docker: a CANCEL stops an agent that ignores SIGINT and SIGTERM (#918).

The agent in #918 ran every phase to completion after the cancel was
delivered. This workload is that agent: it ignores both signals and prints a
stream-json line every 100ms forever. The cancel goes through the production
chain - ``EventStreamProcessor`` polling a controller, ``ManagedWorkspace``,
``AgenticEventStreamAdapter``, ``WorkspaceDockerProvider`` - and the stream is
held open, so nothing but ``interrupt()`` can have stopped it.

    uv run pytest -m integration packages/syn-adapters/tests/test_918_cancel_stops_a_signal_ignoring_agent.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from agentic_isolation import (
    SecurityConfig,
    WorkspaceConfig,
    WorkspaceDockerProvider,
    WorkspaceRuntime,
)

from syn_adapters.control.commands import ControlSignal, ControlSignalType
from syn_adapters.workspace_backends.agentic.credentials import WorkspaceCredentials
from syn_adapters.workspace_backends.agentic.stream_adapter import AgenticEventStreamAdapter
from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationHandle,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)
from syn_shared.settings.session_store import SessionStoreSettings

if TYPE_CHECKING:
    from pathlib import Path

    from agentic_isolation.providers.base import Workspace

IMAGE = os.environ.get("SYN_CONTRACT_TEST_IMAGE", "busybox:1.36")
_MARKER = "syn-918-ignores-signals"
#: The provider's grace (5s), its KILL wait (2s), a container stop and the
#: first cancel poll, with room for a slow runner. Unbounded is the defect.
_BOUND_SECONDS = 45

# `trap "" INT TERM` ignores both, and the ignore is inherited by `sleep`.
_WORKLOAD = [
    "sh",
    "-c",
    'trap "" INT TERM; while :; do echo \'{"type":"system","subtype":"tick"}\'; sleep 0.1; done',
    _MARKER,
]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("docker") is None, reason="requires Docker"),
]


class _Host:
    def __init__(
        self,
        provider: WorkspaceDockerProvider,
        workspace: Workspace,
        credentials: WorkspaceCredentials,
    ) -> None:
        self.operations = provider
        self.credentials = credentials
        self._workspace = workspace

    def workspace(self, isolation_id: str) -> Workspace | None:
        return self._workspace


class _CancellingController:
    async def check_signal(self, execution_id: str) -> ControlSignal:
        return ControlSignal(
            signal_type=ControlSignalType.CANCEL, execution_id=execution_id, reason="user cancel"
        )


def _container_exists(container: str) -> bool:
    inspected = subprocess.run(["docker", "inspect", container], capture_output=True, check=False)
    return inspected.returncode == 0


async def test_a_cancel_stops_an_agent_that_ignores_its_signals(tmp_path: Path) -> None:
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode:
        subprocess.run(["docker", "pull", IMAGE], capture_output=True, check=True)
    credentials = WorkspaceCredentials(SessionStoreSettings(_env_file=None))
    provider = WorkspaceDockerProvider(
        default_image=IMAGE,
        default_network="none",
        workspace_base_dir=tmp_path / "workspaces",
        security=SecurityConfig(runtime=WorkspaceRuntime.RUNC),
        credentials=credentials,
    )
    workspace = await provider.create(
        WorkspaceConfig(provider="docker", image=IMAGE, labels={"syn.test": "cancel-918"})
    )
    container = str(workspace.metadata.get("container_id", workspace.id))
    torn_down = False
    try:
        handle = IsolationHandle(isolation_id=workspace.id, isolation_type="docker")
        service = MagicMock()
        service._event_stream = AgenticEventStreamAdapter(_Host(provider, workspace, credentials))  # type: ignore[arg-type]
        managed = ManagedWorkspace(
            workspace_id=workspace.id,
            execution_id="exec-918",
            aggregate=MagicMock(),
            isolation_handle=handle,
            sidecar_handle=None,
            _service=service,
        )
        processor = EventStreamProcessor(
            tokens=TokenAccumulator(),
            subagents=SubagentTracker(),
            observability=None,
            controller=_CancellingController(),  # type: ignore[arg-type]
            execution_id="exec-918",
            phase_id="phase-1",
            session_id="s-918",
            workspace_id=workspace.id,
            agent_model=None,
        )
        stream = managed.stream(_WORKLOAD, timeout_seconds=600)
        try:
            started = time.monotonic()
            async with asyncio.timeout(_BOUND_SECONDS):
                result = await processor.process_stream(stream, managed)
            elapsed = time.monotonic() - started

            assert result.interrupt_requested
            assert elapsed < _BOUND_SECONDS
            ps = await provider.execute(workspace, "ps -o args", timeout=30)
            assert _MARKER not in ps.stdout, f"the agent outlived its cancel:\n{ps.stdout}"
        finally:
            await stream.aclose()  # type: ignore[attr-defined]

        await provider.teardown(target=workspace)
        torn_down = True
        assert not _container_exists(container), "a cancelled workspace left its container behind"
    finally:
        if not torn_down:
            await provider.teardown(target=workspace)
