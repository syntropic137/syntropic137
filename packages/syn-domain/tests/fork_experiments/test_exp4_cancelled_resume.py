"""EXPERIMENT 4: what does the system DO when a CANCELLED execution is resumed?

Two entry points exist:
  (a) the aggregate's ResumeExecutionCommand handler;
  (b) POST /executions/{id}/resume -> ExecutionController, which never
      touches the aggregate and decides from the detail projection.

Every command handler of the aggregate is also fired at a CANCELLED
execution that has been REHYDRATED from the event store (not the in-memory
instance that did the cancelling), to see what a stale processor could still
append after a cancel.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.control import ExecutionController
from syn_adapters.control.adapters.memory import InMemorySignalQueueAdapter
from syn_adapters.control.adapters.projection import ProjectionControlStateAdapter
from syn_adapters.control.commands import ResumeExecution
from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    AgentExecutionCompletedCommand,
    ArtifactsCollectedCommand,
    CancelExecutionCommand,
    CompleteExecutionCommand,
    CompletePhaseCommand,
    FailExecutionCommand,
    InterruptExecutionCommand,
    PauseExecutionCommand,
    ProvisionWorkspaceCompletedCommand,
    ResumeExecutionCommand,
    RetryPhaseCommand,
    StartPhaseCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
    FailureClassification,
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    StartExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

pytestmark = pytest.mark.unit
EID = "exec-cancelled01"


def _repo(client: MemoryEventStoreClient) -> EventStoreRepository[WorkflowExecutionAggregate]:
    return EventStoreRepository(client, WorkflowExecutionAggregate, "WorkflowExecution")


async def _cancelled(client: MemoryEventStoreClient) -> None:
    repo = _repo(client)
    agg = WorkflowExecutionAggregate()
    agg._handle_command(
        StartExecutionCommand(
            execution_id=EID, workflow_id="wf", workflow_name="W", total_phases=2,
            inputs={"task": "t"},
            phase_definitions=[PhaseDefinition(phase_id="p1", name="P1", order=1),
                               PhaseDefinition(phase_id="p2", name="P2", order=2)],
        )
    )
    agg._handle_command(StartPhaseCommand(execution_id=EID, workflow_id="wf", phase_id="p1",
                                          phase_name="P1", phase_order=1))
    await repo.save_new(agg)
    agg._handle_command(CancelExecutionCommand(execution_id=EID, phase_id="p1", reason="stop"))
    await repo.save(agg)


def _all_commands() -> dict[str, object]:
    return {
        "Resume": ResumeExecutionCommand(execution_id=EID, phase_id="p1"),
        "Pause": PauseExecutionCommand(execution_id=EID, phase_id="p1"),
        "Cancel(again)": CancelExecutionCommand(execution_id=EID, phase_id="p1"),
        "Interrupt": InterruptExecutionCommand(execution_id=EID, phase_id="p1"),
        "StartPhase(p2)": StartPhaseCommand(execution_id=EID, workflow_id="wf", phase_id="p2",
                                            phase_name="P2", phase_order=2),
        "RetryPhase(p1)": RetryPhaseCommand(execution_id=EID, phase_id="p1", reason="r"),
        "CompletePhase(p1)": CompletePhaseCommand(
            execution_id=EID, workflow_id="wf", phase_id="p1", session_id=None, artifact_id=None,
            input_tokens=1, output_tokens=1, cache_creation_tokens=0, cache_read_tokens=0,
            total_tokens=2, duration_seconds=1.0),
        "ProvisionWorkspaceCompleted": ProvisionWorkspaceCompletedCommand(
            execution_id=EID, phase_id="p1", workspace_id="ws"),
        "AgentExecutionCompleted": AgentExecutionCompletedCommand(
            execution_id=EID, phase_id="p1", session_id="s"),
        "ArtifactsCollected": ArtifactsCollectedCommand(
            execution_id=EID, phase_id="p1", artifact_ids=["art-x"]),
        "CompleteExecution": CompleteExecutionCommand(
            execution_id=EID, completed_phases=1, total_phases=2, total_input_tokens=0,
            total_output_tokens=0, total_cache_creation_tokens=0, total_cache_read_tokens=0,
            duration_seconds=1.0, artifact_ids=[]),
        "FailExecution": FailExecutionCommand(
            execution_id=EID, error="e", error_type=None, failed_phase_id="p1",
            completed_phases=0, total_phases=2, classification=next(iter(FailureClassification))),
    }


async def test_every_command_against_a_rehydrated_cancelled_execution() -> None:
    client = MemoryEventStoreClient()
    await _cancelled(client)
    outcomes: dict[str, str] = {}
    for name, cmd in _all_commands().items():
        agg = await _repo(client).load(EID)
        assert agg is not None
        assert agg.status is ExecutionStatus.CANCELLED  # precondition really holds
        try:
            agg._handle_command(cmd)
            emitted = [type(e.event).__name__ for e in agg.get_uncommitted_events()]
            outcomes[name] = f"ACCEPTED -> {emitted} status={agg.status}"
        except Exception as exc:  # noqa: BLE001 - measuring, not handling
            outcomes[name] = f"REJECTED {type(exc).__name__}: {exc}"
    for k, v in outcomes.items():
        print(f"EXP4 aggregate {k}: {v}")
    assert outcomes["Resume"].startswith("REJECTED")


async def test_resume_endpoint_path_on_cancelled_and_on_paused() -> None:
    store = InMemoryProjectionStore()
    proj = WorkflowExecutionDetailProjection(store)
    await proj.on_workflow_execution_started({"execution_id": EID, "workflow_id": "wf",
                                              "inputs": {"task": "t"}, "total_phases": 2})
    await proj.on_execution_cancelled({"execution_id": EID, "phase_id": "p1", "reason": "stop"})
    signals = InMemorySignalQueueAdapter()
    ctl = ExecutionController(ProjectionControlStateAdapter(store), signals)

    res = await ctl.handle_command(ResumeExecution(execution_id=EID))
    queued = await signals.get_signal(EID)
    print(f"EXP4 controller resume on cancelled: success={res.success} state={res.new_state} "
          f"error={res.error!r} queued={queued}")
    assert res.success is False and queued is None

    # Control: prove the controller CAN say yes, so the refusal above is about
    # the state and not a broken harness. "paused" is written by hand because no
    # projection handler writes it (grep: no ExecutionPaused handler).
    row = await store.get(WorkflowExecutionDetailProjection.PROJECTION_NAME, EID)
    row["status"] = "paused"
    await store.save(WorkflowExecutionDetailProjection.PROJECTION_NAME, EID, row)
    res2 = await ctl.handle_command(ResumeExecution(execution_id=EID))
    queued2 = await signals.get_signal(EID)
    print(f"EXP4 controller resume on hand-set paused: success={res2.success} queued={queued2}")
    assert res2.success is True and queued2 is not None

    # Unknown id: projection has no row
    res3 = await ctl.handle_command(ResumeExecution(execution_id="exec-nope"))
    print(f"EXP4 controller resume unknown id: success={res3.success} state={res3.new_state}")
