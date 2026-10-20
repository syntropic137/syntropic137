"""Real Docker: a CANCEL stops an agent that ignores SIGINT and SIGTERM (#918).

The agent in #918 ran every phase to completion after the cancel was
delivered. This workload is that agent: it ignores both signals, prints one
stream-json line and then sleeps forever. The workspace comes from the
production ``WorkspaceService.create_workspace`` over the Docker adapters, the
cancel goes through ``EventStreamProcessor`` polling a controller,
``ManagedWorkspace``, ``AgenticEventStreamAdapter`` and
``WorkspaceDockerProvider``, and the container is removed by the service's own
cleanup - nothing but ``interrupt()`` can have stopped the agent, and nothing
but production cleanup can have removed the container.

    uv run pytest -m integration packages/syn-adapters/tests/test_918_cancel_stops_a_signal_ignoring_agent.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
import uuid
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from agentic_isolation import SecurityConfig

from syn_adapters.control.commands import ControlSignal, ControlSignalType
from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter
from syn_adapters.workspace_backends.agentic.stream_adapter import AgenticEventStreamAdapter
from syn_adapters.workspace_backends.service.workspace_service import (
    WorkspaceService,
    WorkspaceServiceConfig,
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

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace

IMAGE = os.environ.get("SYN_CONTRACT_TEST_IMAGE", "busybox:1.36")
_MARKER = "syn-918-ignores-signals"
#: The provider's grace (5s), its KILL wait (2s), a container stop and the
#: next cancel poll (2s), with room for a slow runner. Unbounded is the defect.
_BOUND_SECONDS = 45
#: Long enough past the first line for several polls to find nothing.
_QUIET_SECONDS = 8

# `trap "" INT TERM` ignores both, and the ignore is inherited by `sleep`.
_WORKLOAD = [
    "sh",
    "-c",
    # One line, then silence: a poll tied to output would never run again (#918 B1).
    'trap "" INT TERM; echo \'{"type":"system","subtype":"init"}\'; while :; do sleep 0.1; done',
    _MARKER,
]

#: Opens what the container identity made under /workspace to the host, so a
#: root image on a non-root runner cannot make teardown report the directory
#: retained (see test_pc126_skill_install_retry_docker.py). Best effort: the
#: escalated cancel may already have stopped the container.
_HAND_BACK_TO_HOST = 'find /workspace -user "$(id -u)" -type d -exec chmod a+rwx {} +'

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("docker") is None, reason="requires Docker"),
]


class _UserCancelsLater:
    """No signal until ``cancel()``; then CANCEL with no reason, as the API sends it."""

    def __init__(self) -> None:
        self.pending = False

    def cancel(self) -> None:
        self.pending = True

    async def check_signal(self, execution_id: str) -> ControlSignal | None:
        if not self.pending:
            return None
        return ControlSignal(signal_type=ControlSignalType.CANCEL, execution_id=execution_id)


def _containers_of(execution_id: str) -> list[str]:
    """Every container, running or not, the adapter labelled with this execution."""
    listed = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label=syn.execution_id={execution_id}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return listed.stdout.split()


def _docker_service(tmp_path: Path) -> WorkspaceService:
    """The Docker wiring of ``WorkspaceService._create_docker_impl``, minus the proxy.

    The sidecar and token injection are never reached: the workspace is
    created ``with_sidecar=False`` and ``inject_tokens=False``.
    """
    isolation = AgenticIsolationAdapter(
        default_image=IMAGE,
        security=SecurityConfig.development(),
        workspace_container_dir=str(tmp_path / "workspaces"),
        session_store=SessionStoreSettings(_env_file=None),
    )
    return WorkspaceService(
        isolation=isolation,  # type: ignore[arg-type]
        sidecar=MagicMock(),
        token_injection=MagicMock(),
        event_stream=AgenticEventStreamAdapter(isolation),
        config=WorkspaceServiceConfig(image=IMAGE),
    )


async def _passthrough(image_ref: str) -> str:
    return image_ref


async def test_a_cancel_stops_an_agent_that_ignores_its_signals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode:
        subprocess.run(["docker", "pull", IMAGE], capture_output=True, check=True)
    # The default agent-net only exists inside a deployment.
    monkeypatch.setenv("SYN_AGENT_NETWORK", "none")
    service = _docker_service(tmp_path)
    execution_id = f"exec-918-{uuid.uuid4().hex[:12]}"
    try:
        # The supply-chain gate refuses an unpinned public image; it is not what
        # is under test here (tests/workspace_backends/test_image_verification.py).
        with patch(
            "syn_adapters.workspace_backends.backend_kit.verify_image_async",
            side_effect=_passthrough,
        ):
            async with service.create_workspace(
                execution_id=execution_id,
                phase_id="phase-1",
                with_sidecar=False,
                # Nothing for the root image to write under /workspace.
                extra_environment={"TMPDIR": "/tmp"},
            ) as managed:
                assert _containers_of(execution_id), "the service created no container"
                await _cancel_the_running_agent(managed, execution_id)
                await managed.execute(["sh", "-c", _HAND_BACK_TO_HOST], timeout_seconds=30)

        # Production cleanup alone, before the fallback below can hide a leak.
        left = _containers_of(execution_id)
        assert not left, (
            f"a cancelled workspace left its container behind: {left} "
            f"(teardown_failure={managed.teardown_failure})"
        )
    finally:
        # Only for a failed run: the assertion above has already checked cleanup.
        for container in _containers_of(execution_id):
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)


async def _cancel_the_running_agent(managed: ManagedWorkspace, execution_id: str) -> None:
    """Cancel the trapped workload mid-stream; it must stop within the bound."""
    controller = _UserCancelsLater()
    processor = EventStreamProcessor(
        tokens=TokenAccumulator(),
        subagents=SubagentTracker(),
        observability=None,
        controller=controller,  # type: ignore[arg-type]
        execution_id=execution_id,
        phase_id="phase-1",
        session_id="s-918",
        workspace_id=managed.workspace_id,
        agent_model=None,
    )
    stream = managed.stream(_WORKLOAD, timeout_seconds=600)
    try:
        task = asyncio.create_task(processor.process_stream(stream, managed))
        # Let it start, speak, and go quiet before the user cancels.
        await asyncio.sleep(_QUIET_SECONDS)
        assert not task.done(), "the workload ended before it was cancelled"
        controller.cancel()
        started = time.monotonic()
        # The timeout only fails the test; the stop must come from cancel.
        async with asyncio.timeout(_BOUND_SECONDS * 2):
            result = await task
        elapsed = time.monotonic() - started

        assert result.interrupt_requested
        assert result.interrupt_reason is None
        assert elapsed < _BOUND_SECONDS, f"cancel took {elapsed:.1f}s"
        ps = await managed.execute(["ps", "-o", "args"], timeout_seconds=30)
        assert _MARKER not in ps.stdout, f"the agent outlived its cancel:\n{ps.stdout}"
    finally:
        await stream.aclose()  # type: ignore[attr-defined]
