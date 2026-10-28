"""A command Phase rides the same to-do list as an agent Phase (ADR-078 D3, D5).

`PhaseCommandsCompleted` queues collection whatever the gate said, so a failed
build's logs are kept; the `WorkflowFailed` the aggregate then writes clears
the list, so no `COMPLETE_PHASE` and no later phase ever runs.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration._shared.CommandStepValueObjects import (
    CommandStepOutcome,
    CommandStepResult,
)
from syn_domain.contexts.orchestration.domain.events.PhaseCommandsCompletedEvent import (
    PhaseCommandsCompletedEvent,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.contexts.orchestration.slices.execution_todo.value_objects import TodoAction

pytestmark = pytest.mark.unit

STARTED = {
    "execution_id": "exec-1",
    "workflow_id": "wf-1",
    "workflow_name": "Probe",
    "total_phases": 2,
    "started_at": "2026-10-27T00:00:00Z",
    "inputs": {},
    "phase_definitions": [
        {"phase_id": "build", "name": "Build", "order": 1, "timeout_seconds": 300},
        {"phase_id": "review", "name": "Review", "order": 2, "timeout_seconds": 300},
    ],
}


def _commands_completed(*, success: bool) -> dict[str, object]:
    outcome = CommandStepOutcome.PASSED if success else CommandStepOutcome.FAILED
    event = PhaseCommandsCompletedEvent(
        workflow_id="wf-1",
        execution_id="exec-1",
        phase_id="build",
        workspace_id="ws-1",
        completed_at=datetime(2026, 10, 27, tzinfo=UTC),
        success=success,
        steps=[
            CommandStepResult(name="cargo-build", outcome=outcome, exit_code=0 if success else 101)
        ],
    )
    # What the subscription delivers: the stored payload, not the model.
    return event.model_dump(mode="json")


async def _ran_build(proj: ExecutionTodoProjection) -> None:
    await proj.on_workflow_execution_started(STARTED)
    await proj.on_workspace_provisioned_for_phase(
        {"execution_id": "exec-1", "phase_id": "build", "workspace_id": "ws-1"}
    )


@pytest.mark.anyio
@pytest.mark.parametrize("success", [True, False])
async def test_commands_completed_queues_collection_whatever_the_gate_said(
    success: bool,
) -> None:
    proj = ExecutionTodoProjection(store=InMemoryProjectionStore())
    await _ran_build(proj)

    await proj.on_phase_commands_completed(_commands_completed(success=success))  # type: ignore[arg-type]  # the coordinator delivers the stored dict

    [todo] = await proj.get_pending("exec-1")
    assert todo.action == TodoAction.COLLECT_ARTIFACTS
    assert todo.phase_id == "build"
    assert todo.session_id is None


@pytest.mark.anyio
async def test_the_gate_failure_clears_the_list_so_nothing_after_it_runs() -> None:
    proj = ExecutionTodoProjection(store=InMemoryProjectionStore())
    await _ran_build(proj)
    await proj.on_phase_commands_completed(_commands_completed(success=False))  # type: ignore[arg-type]  # the coordinator delivers the stored dict

    # The aggregate's one save at collection: collected, then failed.
    await proj.on_artifacts_collected_for_phase({"execution_id": "exec-1", "phase_id": "build"})
    await proj.on_workflow_failed({"execution_id": "exec-1"})

    assert await proj.get_pending("exec-1") == []
