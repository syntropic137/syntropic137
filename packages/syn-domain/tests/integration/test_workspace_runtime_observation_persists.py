"""A phase workspace's runtime row survives the phase, in real TimescaleDB (SYN-1).

The unit suite (`test_workspace_runtime_observation.py`) pins the payload at
the recorder boundary with an in-memory writer, which never executes the
production write. This writes through the production seam
(`PhaseRuntime.record_runtime` -> `AgentEventStore.record_observation`), ends
the phase as a failure so the workspace scope is gone, closes the writer, and
reads the row back through a fresh store.

The workspace asks for auto and got gVisor: requested and effective differ, so
a row that wrote one field from the other's source fails here.

Uses the shared `test_infrastructure` fixture (ADR-034): test-stack on port
15432, else testcontainers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationRuntime,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import PhaseRuntime
from syn_shared.events import WORKSPACE_RUNTIME
from syn_shared.settings.workspace import WorkspaceRuntime

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

PHASE = "p-runtime"


@dataclass(frozen=True)
class _Handle:
    runtime: IsolationRuntime | None


class _Workspace:
    teardown_usage = None

    def __init__(self, execution_id: str, workspace_id: str) -> None:
        self.execution_id = execution_id
        self.workspace_id = workspace_id
        self.isolation_handle = _Handle(
            IsolationRuntime(requested=None, effective=WorkspaceRuntime.GVISOR)
        )


class _WorkspaceCm:
    async def __aexit__(self, *_exc: object) -> bool:
        return False


async def test_the_runtime_row_is_persisted_and_outlives_a_failed_phase(test_infrastructure):
    from syn_adapters.events import AgentEventStore

    session_id = f"s-runtime-{uuid4()}"
    execution_id = f"e-runtime-{uuid4()}"
    workspace_id = f"w-runtime-{uuid4()}"

    writer = AgentEventStore(test_infrastructure.timescaledb_url)
    await writer.initialize()
    try:
        phase_runtime = PhaseRuntime(
            capture_port=None, session_store=None, writer=writer, ledger=None
        )
        phase_runtime.attach_workspace(
            PHASE,
            workspace=cast("ManagedWorkspace", _Workspace(execution_id, workspace_id)),
            workspace_cm=cast("AbstractAsyncContextManager[ManagedWorkspace]", _WorkspaceCm()),
            agent_env={},
            claude_cmd=[],
            delivers_repo_changes=False,
        )
        phase_runtime.launch(PHASE, session_id=session_id)
        await phase_runtime.record_runtime(PHASE)
        await phase_runtime.abandon_phase(execution_id, PHASE, reason="agent crashed")
    finally:
        await writer.close()

    reader = AgentEventStore(test_infrastructure.timescaledb_url)
    await reader.initialize()
    try:
        rows = await reader.query(session_id, event_type=WORKSPACE_RUNTIME)
    finally:
        await reader.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] == session_id
    assert row["execution_id"] == execution_id
    assert row["phase_id"] == PHASE
    assert row["data"]["workspace_id"] == workspace_id
    assert row["data"]["runtime_requested"] == "auto"
    assert row["data"]["runtime_effective"] == "gvisor"
