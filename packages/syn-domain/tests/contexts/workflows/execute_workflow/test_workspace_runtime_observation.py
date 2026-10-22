"""A phase workspace's resolved runtime is a Lane 2 observation (SYN-1).

The runtime is agentic-workspace's resolver's answer, carried on the isolation
handle. It is written as the agent launches, the first moment the session id is
known, so a phase that fails afterwards still leaves the row. The fixture asks
for auto and gets gVisor: requested and effective differ, so a row that wrote
one field from the other's source fails here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from syn_domain.contexts.agent_sessions import ObservationType
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationRuntime,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import PhaseRuntime
from syn_shared.events import VALID_EVENT_TYPES, WORKSPACE_RUNTIME
from syn_shared.settings.workspace import WorkspaceRuntime

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace

pytestmark = pytest.mark.unit

PHASE = "p-runtime"
SESSION = "s-runtime"
AUTO_GOT_GVISOR = IsolationRuntime(requested=None, effective=WorkspaceRuntime.GVISOR)


@dataclass(frozen=True)
class _Handle:
    runtime: IsolationRuntime | None


class _Workspace:
    execution_id = "e-runtime"
    workspace_id = "w-runtime"
    teardown_usage = None

    def __init__(self, runtime: IsolationRuntime | None) -> None:
        self.isolation_handle = _Handle(runtime)


class _WorkspaceCm:
    async def __aexit__(self, *_exc: object) -> bool:
        return False


@dataclass(frozen=True)
class _Row:
    session_id: str
    observation_type: ObservationType | str
    data: object
    execution_id: str | None
    phase_id: str | None
    workspace_id: str | None


class _Writer:
    def __init__(self, *, fail: BaseException | None = None) -> None:
        self.rows: list[_Row] = []
        self._fail = fail

    async def record_observation(
        self,
        session_id: str,
        observation_type: ObservationType | str,
        data: object,
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        if self._fail is not None:
            raise self._fail
        self.rows.append(
            _Row(session_id, observation_type, data, execution_id, phase_id, workspace_id)
        )

    def runtime_rows(self) -> list[_Row]:
        return [r for r in self.rows if r.observation_type == ObservationType.WORKSPACE_RUNTIME]


def _launched(writer: _Writer, runtime: IsolationRuntime | None) -> PhaseRuntime:
    phase_runtime = PhaseRuntime(capture_port=None, session_store=None, writer=writer, ledger=None)
    phase_runtime.attach_workspace(
        PHASE,
        workspace=cast("ManagedWorkspace", _Workspace(runtime)),
        workspace_cm=cast("AbstractAsyncContextManager[ManagedWorkspace]", _WorkspaceCm()),
        agent_env={},
        claude_cmd=[],
        delivers_repo_changes=False,
    )
    phase_runtime.launch(PHASE, session_id=SESSION)
    return phase_runtime


_EXPECTED = _Row(
    session_id=SESSION,
    observation_type=ObservationType.WORKSPACE_RUNTIME,
    data={"runtime_requested": "auto", "runtime_effective": "gvisor"},
    execution_id="e-runtime",
    phase_id=PHASE,
    workspace_id="w-runtime",
)


@pytest.mark.asyncio
async def test_launch_records_requested_and_effective_runtime() -> None:
    writer = _Writer()

    await _launched(writer, AUTO_GOT_GVISOR).record_runtime(PHASE)

    assert writer.runtime_rows() == [_EXPECTED]


@pytest.mark.asyncio
async def test_the_row_survives_the_phase_failing_afterwards() -> None:
    writer = _Writer()
    phase_runtime = _launched(writer, AUTO_GOT_GVISOR)

    await phase_runtime.record_runtime(PHASE)
    await phase_runtime.abandon_phase("e-runtime", PHASE, reason="agent crashed")

    assert writer.runtime_rows() == [_EXPECTED]


@pytest.mark.asyncio
async def test_a_failed_write_does_not_fail_the_phase() -> None:
    writer = _Writer(fail=ConnectionError("observability store down"))

    await _launched(writer, AUTO_GOT_GVISOR).record_runtime(PHASE)

    assert writer.rows == []


@pytest.mark.asyncio
async def test_a_backend_with_no_runtime_records_nothing() -> None:
    writer = _Writer()

    await _launched(writer, None).record_runtime(PHASE)

    assert writer.rows == []


def test_the_write_path_accepts_the_type() -> None:
    """`VALID_EVENT_TYPES` gates the store: a type missing there fails at write."""
    assert str(ObservationType.WORKSPACE_RUNTIME) == WORKSPACE_RUNTIME
    assert WORKSPACE_RUNTIME in VALID_EVENT_TYPES
