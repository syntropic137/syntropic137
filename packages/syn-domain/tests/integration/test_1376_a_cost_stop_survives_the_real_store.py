"""A phase's cost limit, and a cost stop, read back from the REAL event store (#1376).

The unit tests round-trip events through JSON in-process. This drives the same
facts through the ESP server, because that is what a resume actually reads:
the limit pinned on the parent's start event, the FAILED status a cost stop
leaves, and the resume's start command built from that stream alone. If any of
them did not survive the store, a resumed phase would run unbounded, or a
cost-stopped execution would refuse resume.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
    phase_definitions_of,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    ExecutionStatus,
    FailureClassification,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    FailExecutionCommand,
    ResumeExecutionCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)

if TYPE_CHECKING:
    from event_sourcing import EventStoreRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_LIMIT = 7.5
_REASON = "Phase experiment stopped: cost limit USD 7.50 exceeded at USD 7.61"


async def test_a_cost_stopped_phase_resumes_under_the_limit_it_started_with(
    workflow_execution_repository: EventStoreRepository[WorkflowExecutionAggregate],
    unique_execution_id: str,
) -> None:
    pinned = [
        ExecutablePhase(
            phase_id="experiment",
            name="Experiment",
            order=1,
            agent_config=AgentConfiguration(model="claude-sonnet-4-5"),
            prompt_template="probe",
            max_cost_usd=_LIMIT,
        )
    ]
    parent = WorkflowExecutionAggregate()
    parent._handle_command(
        StartExecutionCommand(
            execution_id=unique_execution_id,
            workflow_id="wf-1376",
            workflow_name="Cost limit",
            total_phases=1,
            inputs={},
            phase_definitions=phase_definitions_of(pinned),
            pinned_phases=pinned,
        )
    )
    await workflow_execution_repository.save(parent)

    loaded = await workflow_execution_repository.load(unique_execution_id)
    assert loaded is not None
    loaded.start_phase(
        StartPhaseCommand(
            execution_id=unique_execution_id,
            workflow_id="wf-1376",
            phase_id="experiment",
            phase_name="Experiment",
            phase_order=1,
        )
    )
    loaded._handle_command(
        FailExecutionCommand(
            execution_id=unique_execution_id,
            error=_REASON,
            error_type="PhaseCostLimitExceededError",
            failed_phase_id="experiment",
            completed_phases=0,
            total_phases=1,
            classification=FailureClassification.PLATFORM,
        )
    )
    await workflow_execution_repository.save(loaded)

    failed = await workflow_execution_repository.load(unique_execution_id)
    assert failed is not None
    assert failed.status == ExecutionStatus.FAILED
    assert failed._error == _REASON

    failed.resume_execution(
        ResumeExecutionCommand(
            execution_id=unique_execution_id,
            resume_execution_id=f"{unique_execution_id}-resume",
            acknowledge_external_effects=True,
        )
    )
    await workflow_execution_repository.save(failed)

    admitted = await workflow_execution_repository.load(unique_execution_id)
    assert admitted is not None
    start = admitted.resume_start_command()
    assert start.resumed_from.resume_phase_id == "experiment"
    assert [p.max_cost_usd for p in start.pinned_phases] == [_LIMIT]
