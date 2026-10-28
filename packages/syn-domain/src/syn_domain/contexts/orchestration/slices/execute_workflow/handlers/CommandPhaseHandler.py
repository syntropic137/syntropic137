"""Runs a command Phase's fixed shell steps: no agent, no session, 0 tokens (ADR-078 D3, D4).

The processor's RUN_AGENT routes here by ``phase.kind``. Steps run in order in
the Phase's own Workspace under ONE monotonic deadline, set as the first step
starts; each step gets ``min(its own timeout, what remains)``. The handler
decides nothing about the Execution: it records what each step did, and the
aggregate judges that record at collection (D5).

A cancel is polled beside every step, quiet or noisy, exactly as beside an
agent's stream (#918). It interrupts the step, skips the rest, and is returned
to the caller rather than recorded: a cancelled Phase has no
``PhaseCommandsCompleted``, it has an ``ExecutionCancelled``.
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from syn_domain.contexts.orchestration._shared.command_phase import CommandTerminal
from syn_domain.contexts.orchestration._shared.CommandStepValueObjects import CommandStepOutcome
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    RecordPhaseCommandsCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CancelSignalPoller import (
    CANCEL_POLL_SECONDS,
    CancelSignalPoller,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.command_report import (
    CommandsReport,
    CommandStepReport,
)
from syn_shared.workspace_paths import WORKSPACE_ROOT

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from syn_adapters.control import ExecutionController
    from syn_domain.contexts.orchestration._shared.command_phase import (
        BoundedCommandResult,
        CommandStep,
    )
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.ports.CommandWorkspacePort import (
        CommandWorkspacePort,
    )

#: Steps run where the workspace's repositories are checked out under.
_STEP_DIRECTORY: Final = str(WORKSPACE_ROOT)

_ENDED: Final = {
    CommandTerminal.TIMED_OUT: CommandStepOutcome.TIMED_OUT,
    CommandTerminal.INTERRUPTED: CommandStepOutcome.INTERRUPTED,
    CommandTerminal.FAILED_TO_START: CommandStepOutcome.FAILED_TO_START,
}


def step_outcome(result: BoundedCommandResult) -> CommandStepOutcome:
    """How a step ended, from the transport's typed terminal and never the exit code alone."""
    if result.terminal is CommandTerminal.EXITED:
        return CommandStepOutcome.PASSED if result.exit_code == 0 else CommandStepOutcome.FAILED
    return _ENDED[result.terminal]


@dataclass(frozen=True)
class CommandPhaseRun:
    """What the steps did. ``cancelled`` is the reason when a cancel stopped them."""

    report: CommandsReport
    cancelled: str | None = None


@dataclass
class CommandPhaseHandler:
    """Stateless across executions: the processor shares one."""

    controller: ExecutionController | None
    clock: Callable[[], float] = time.monotonic
    poll_seconds: float = CANCEL_POLL_SECONDS
    wall_clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    async def run(
        self,
        todo: TodoItem,
        phase: ExecutablePhase,
        workspace: CommandWorkspacePort,
        aggregate: WorkflowExecutionAggregate,
        save: Callable[[WorkflowExecutionAggregate], Awaitable[None]],
    ) -> CommandPhaseRun:
        """Run every step, write the report into the workspace, record it unless cancelled."""
        assert todo.phase_id is not None, "a command phase to-do names its phase"
        poller = CancelSignalPoller(
            self.controller, todo.execution_id, poll_seconds=self.poll_seconds
        )
        steps = _Steps(self, workspace, poller, budget=phase.effective_timeout_seconds)
        for step in phase.commands:
            await steps.run(step)
        report = steps.report(todo.phase_id)
        # Written before recording, cancelled or not: the report is the
        # Phase's primary artifact and a cancel still keeps what ran (D3, D7).
        await workspace.inject_files(report.files())
        if steps.cancelled is None:
            aggregate.record_phase_commands(
                RecordPhaseCommandsCommand(
                    execution_id=todo.execution_id,
                    phase_id=todo.phase_id,
                    workspace_id=workspace.workspace_id,
                    success=report.success,
                    timed_out=report.timed_out,
                    steps=[step.recorded() for step in report.steps],
                )
            )
            await save(aggregate)
        return CommandPhaseRun(report=report, cancelled=steps.cancelled)


@dataclass
class _Steps:
    """One Phase's worth of steps: the deadline, what ran, and whether to go on."""

    h: CommandPhaseHandler
    workspace: CommandWorkspacePort
    poller: CancelSignalPoller
    budget: int
    results: list[CommandStepReport] = field(default_factory=list)
    timed_out: bool = False
    cancelled: str | None = None
    stopped: bool = False
    _deadline: float | None = None

    def _allowance(self, step: CommandStep) -> tuple[int, int]:
        """(this step's bound, what remains of the Phase); the deadline starts with step one."""
        if self._deadline is None:
            self._deadline = self.h.clock() + self.budget
        remaining = math.floor(self._deadline - self.h.clock())
        if step.timeout_seconds is None:
            return remaining, remaining
        return min(step.timeout_seconds, remaining), remaining

    async def run(self, step: CommandStep) -> None:
        allowed, remaining = self._allowance(step)
        if not self.stopped and allowed <= 0:
            self.timed_out = self.stopped = True
        if not self.stopped:
            await self._check_cancel()
        if self.stopped:
            self._record(step, CommandStepOutcome.SKIPPED)
            return
        result = await self._bounded(step, allowed, remaining)
        outcome = step_outcome(result)
        # Its own timeout is excusable; the Phase's deadline never is (D4).
        if outcome is CommandStepOutcome.TIMED_OUT and allowed == remaining:
            self.timed_out = True
        recorded = self._record(step, outcome, result)
        self.stopped = self.timed_out or self.cancelled is not None or recorded.stops_the_phase

    async def _check_cancel(self) -> None:
        polled = await self.poller.poll(len(self.results))
        if polled.should_interrupt:
            self.cancelled = polled.reason or "Cancelled by user"
            self.stopped = True

    async def _bounded(
        self, step: CommandStep, allowed: int, remaining: int
    ) -> BoundedCommandResult:
        task = asyncio.ensure_future(
            self.workspace.run_bounded(
                ["sh", "-c", step.run],
                timeout_seconds=allowed,
                working_directory=_STEP_DIRECTORY,
                phase_deadline=self.h.wall_clock() + timedelta(seconds=remaining),
            )
        )
        while self.cancelled is None:
            done, _ = await asyncio.wait({task}, timeout=self.poller.poll_seconds)
            if done:
                break
            await self._check_cancel()
            if self.cancelled is not None:
                await self.workspace.interrupt()
        return await task

    def _record(
        self,
        step: CommandStep,
        outcome: CommandStepOutcome,
        result: BoundedCommandResult | None = None,
    ) -> CommandStepReport:
        recorded = CommandStepReport(
            name=step.name,
            outcome=outcome,
            exit_code=None if result is None else result.exit_code,
            duration_ms=0 if result is None else result.duration_ms,
            allow_failure=step.allow_failure,
            tail="" if result is None else result.tail,
            dropped_bytes=0 if result is None else result.dropped_bytes,
        )
        self.results.append(recorded)
        return recorded

    def report(self, phase_id: str) -> CommandsReport:
        failed = any(step.stops_the_phase for step in self.results)
        return CommandsReport(
            phase_id=phase_id,
            success=not (failed or self.timed_out or self.cancelled is not None),
            timed_out=self.timed_out,
            steps=tuple(self.results),
        )
