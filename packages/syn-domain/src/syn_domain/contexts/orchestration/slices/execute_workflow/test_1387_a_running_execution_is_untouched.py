"""Maintenance mode gates admission, not execution (#1387).

The flag exists so a deploy can stop new work arriving and then wait for the
work already accepted to finish. If setting it disturbed a run in progress it
would defeat its own purpose: the drain would never reach zero honestly,
because the executions it was waiting for would have been killed by the same
call that was supposed to protect them.

The distinction lives in ONE fact - the gate is consulted at the top of
`handle()` and never again - and that fact is invisible in a test where the
run completes before the flag is set. So the run below is suspended INSIDE the
processor while the flag flips, which is exactly the window a deploy occupies.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts._shared.maintenance import (
    AdmissionTicket,
    MaintenanceMode,
    MaintenancePausedError,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
    ExecuteWorkflowCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    WorkflowExecutionResult,
)

if TYPE_CHECKING:
    from syn_domain.contexts._shared.repository_ref import RepositoryRef
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )

pytestmark = pytest.mark.unit

_WORKFLOW_ID = "wf-long-running"

#: Long enough that a loaded machine never trips it, short enough that a
#: mutation which refuses admission fails here instead of hanging CI forever.
_REACHES_THE_PROCESSOR = 5.0


async def _started(processor: _SuspendedProcessor) -> None:
    async with asyncio.timeout(_REACHES_THE_PROCESSOR):
        await processor.running.wait()


class _Gate:
    """The maintenance port, flipped by the test rather than by the API.

    Counts reads, because "checked once, at admission" is the property under
    test and a second read is how it would stop being true.
    """

    def __init__(self) -> None:
        self.mode = MaintenanceMode()
        self.reads = 0

    async def current(self) -> MaintenanceMode:
        self.reads += 1
        return self.mode

    async def set_mode(self, *, active: bool, reason: str, actor: str) -> MaintenanceMode:
        self.mode = MaintenanceMode(
            active=active,
            reason=reason,
            actor=actor,
            since=datetime.now(UTC) if active else None,
        )
        return self.mode


class _SuspendedProcessor:
    """Stops mid-execution so the test can close the gate underneath it."""

    def __init__(self) -> None:
        self.running = asyncio.Event()
        self.may_finish = asyncio.Event()

    async def run(
        self,
        *,
        workflow_id: str,
        workflow_name: str,
        phases: list[ExecutablePhase],
        inputs: dict[str, str],
        execution_id: str,
        repos: list[RepositoryRef],
    ) -> WorkflowExecutionResult:
        del workflow_name, phases, inputs, repos
        self.running.set()
        await self.may_finish.wait()
        return WorkflowExecutionResult(
            workflow_id=workflow_id,
            execution_id=execution_id,
            status="completed",
            started_at=datetime.now(UTC),
        )


class _ImmediateProcessor:
    """Never blocks, so a test that expects a refusal cannot hang waiting."""

    def __init__(self) -> None:
        self.runs = 0

    async def run(
        self,
        *,
        workflow_id: str,
        workflow_name: str,
        phases: list[ExecutablePhase],
        inputs: dict[str, str],
        execution_id: str,
        repos: list[RepositoryRef],
    ) -> WorkflowExecutionResult:
        del workflow_name, phases, inputs, repos
        self.runs += 1
        return WorkflowExecutionResult(
            workflow_id=workflow_id,
            execution_id=execution_id,
            status="completed",
            started_at=datetime.now(UTC),
        )


class _Repo:
    def __init__(self) -> None:
        self._workflow = WorkflowTemplateAggregate()

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
        return self._workflow if aggregate_id == _WORKFLOW_ID else None


def _handler(gate: _Gate, processor: object) -> ExecuteWorkflowHandler:
    return ExecuteWorkflowHandler(
        processor=processor,  # type: ignore[arg-type]
        workflow_repository=_Repo(),  # type: ignore[arg-type]
        maintenance=gate,
    )


class TestAnExecutionAlreadyRunningWhenTheGateCloses:
    async def test_completes_normally(self) -> None:
        gate = _Gate()
        processor = _SuspendedProcessor()
        admitted = asyncio.create_task(
            _handler(gate, processor).handle(ExecuteWorkflowCommand(aggregate_id=_WORKFLOW_ID))
        )

        await _started(processor)
        await gate.set_mode(active=True, reason="pit stop", actor="deploy")
        processor.may_finish.set()

        result = await admitted
        assert result.status == "completed"

    async def test_is_not_re_asked_for_permission(self) -> None:
        """One read, at admission. A gate re-consulted mid-run would be able to
        refuse work it had already accepted."""
        gate = _Gate()
        processor = _SuspendedProcessor()
        admitted = asyncio.create_task(
            _handler(gate, processor).handle(ExecuteWorkflowCommand(aggregate_id=_WORKFLOW_ID))
        )

        await _started(processor)
        await gate.set_mode(active=True, reason="pit stop", actor="deploy")
        processor.may_finish.set()
        await admitted

        assert gate.reads == 1


class TestTheNextExecutionAfterThat:
    """The negative control: the flag the running execution ignored is the same
    flag that refuses the next one."""

    async def test_is_refused(self) -> None:
        gate = _Gate()
        await gate.set_mode(active=True, reason="pit stop", actor="deploy")
        processor = _ImmediateProcessor()

        with pytest.raises(MaintenancePausedError):
            await _handler(gate, processor).handle(
                ExecuteWorkflowCommand(aggregate_id=_WORKFLOW_ID)
            )

        assert processor.runs == 0, "refused, but the execution ran anyway"


class TestAnExecutionThatArrivesWithATicket:
    """The gate already said yes, under its transition lock, and the caller has
    already been told so - a 200, or a ``dispatched`` trigger record.

    Everything here runs inside a fire-and-forget task whose exceptions are
    logged and dropped, so re-deciding the admission cannot refuse the work. It
    can only delete it, leaving the record that was written from the first
    answer describing a run that no longer exists. That is the defect
    verification found on the first pass at #1387, and it is why a ticket is
    carried in rather than the flag being read again.
    """

    async def test_is_not_re_asked_for_permission(self) -> None:
        gate = _Gate()
        await gate.set_mode(active=True, reason="pit stop", actor="deploy")
        processor = _ImmediateProcessor()

        result = await _handler(gate, processor).handle(
            ExecuteWorkflowCommand(aggregate_id=_WORKFLOW_ID),
            admitted=AdmissionTicket(granted_at=datetime.now(UTC), mode=MaintenanceMode()),
        )

        assert result.status == "completed"
        assert processor.runs == 1
        assert gate.reads == 0, (
            "the handler re-read the flag for an execution the gate had already "
            "admitted; under a deploy that silently discards the work"
        )

    async def test_the_same_command_without_one_is_refused(self) -> None:
        """The negative control, and the safe default: no ticket means nobody
        asked the gate, so the handler asks."""
        gate = _Gate()
        await gate.set_mode(active=True, reason="pit stop", actor="deploy")
        processor = _ImmediateProcessor()

        with pytest.raises(MaintenancePausedError):
            await _handler(gate, processor).handle(
                ExecuteWorkflowCommand(aggregate_id=_WORKFLOW_ID), admitted=None
            )

        assert processor.runs == 0
