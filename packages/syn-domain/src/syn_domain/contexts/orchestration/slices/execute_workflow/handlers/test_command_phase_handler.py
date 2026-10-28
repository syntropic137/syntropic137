"""CommandPhaseHandler runs the author's steps and records them, deciding nothing (ADR-078 D3, D4)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_domain.contexts.orchestration._shared.command_phase import (
    BoundedCommandResult,
    CommandStep,
    CommandTerminal,
    PhaseKind,
)
from syn_domain.contexts.orchestration._shared.CommandStepValueObjects import CommandStepOutcome
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.command_report import (
    COMMANDS_REPORT_PATH,
    CommandsReport,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.CommandPhaseHandler import (
    CommandPhaseHandler,
)

if TYPE_CHECKING:
    from datetime import datetime

    from syn_adapters.control import ExecutionController
    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        RecordPhaseCommandsCommand,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )


def _exited(code: int, tail: str = "") -> BoundedCommandResult:
    return BoundedCommandResult(
        terminal=CommandTerminal.EXITED, exit_code=code, duration_ms=5, tail=tail
    )


def _ended(terminal: CommandTerminal) -> BoundedCommandResult:
    return BoundedCommandResult(terminal=terminal, duration_ms=5)


@dataclass
class _Call:
    command: list[str]
    timeout_seconds: int
    working_directory: str | None


@dataclass
class _Workspace:
    """Answers each step from a script, in order; a step may block until interrupted."""

    answers: list[BoundedCommandResult | None]
    clock: _Clock | None = None
    spends: int = 0
    calls: list[_Call] = field(default_factory=list)
    files: list[tuple[str, bytes]] = field(default_factory=list)
    interrupted: asyncio.Event = field(default_factory=asyncio.Event)
    workspace_id: str = "ws-1"

    async def run_bounded(
        self,
        command: list[str],
        *,
        timeout_seconds: int,
        working_directory: str | None = None,
        phase_deadline: datetime | None = None,
    ) -> BoundedCommandResult:
        self.calls.append(_Call(command, timeout_seconds, working_directory))
        if self.clock is not None:
            self.clock.now += self.spends
        answer = self.answers.pop(0)
        if answer is None:
            await self.interrupted.wait()
            return _ended(CommandTerminal.INTERRUPTED)
        return answer

    async def inject_files(self, files: list[tuple[str, bytes]]) -> None:
        self.files.extend(files)

    async def interrupt(self) -> bool:
        self.interrupted.set()
        return True


@dataclass
class _Clock:
    now: float = 1000.0

    def __call__(self) -> float:
        return self.now


@dataclass
class _Aggregate:
    recorded: list[RecordPhaseCommandsCommand] = field(default_factory=list)

    def record_phase_commands(self, command: RecordPhaseCommandsCommand) -> None:
        self.recorded.append(command)


def _phase(*steps: CommandStep, timeout: int = 600) -> ExecutablePhase:
    return ExecutablePhase(
        phase_id="build",
        name="Build",
        order=1,
        kind=PhaseKind.COMMAND,
        commands=steps,
        timeout_seconds=timeout,
    )


_TODO = TodoItem(execution_id="exec-1", action=TodoAction.RUN_AGENT, phase_id="build")


async def _run(
    workspace: _Workspace,
    phase: ExecutablePhase,
    *,
    controller: ExecutionController | None = None,
    clock: _Clock | None = None,
) -> tuple[_Aggregate, AsyncMock, CommandsReport, str | None]:
    aggregate = _Aggregate()
    save = AsyncMock()
    handler = CommandPhaseHandler(
        controller=controller,
        clock=clock or _Clock(),
        poll_seconds=0.01,
    )
    run = await handler.run(
        _TODO, phase, workspace, cast("WorkflowExecutionAggregate", aggregate), save
    )
    return aggregate, save, run.report, run.cancelled


def _outcomes(report: CommandsReport) -> list[CommandStepOutcome]:
    return [step.outcome for step in report.steps]


@pytest.mark.unit
class TestCommandPhaseHandler:
    @pytest.mark.asyncio
    async def test_every_step_runs_in_order_as_sh_c_in_the_workspace(self) -> None:
        workspace = _Workspace([_exited(0, "built\n"), _exited(0)])
        phase = _phase(
            CommandStep(name="build", run="make"), CommandStep(name="test", run="make test")
        )

        aggregate, save, report, cancelled = await _run(workspace, phase)

        assert [c.command for c in workspace.calls] == [
            ["sh", "-c", "make"],
            ["sh", "-c", "make test"],
        ]
        assert {c.working_directory for c in workspace.calls} == {"/workspace"}
        assert report.success and not report.timed_out and cancelled is None
        assert _outcomes(report) == [CommandStepOutcome.PASSED, CommandStepOutcome.PASSED]
        (command,) = aggregate.recorded
        assert command.success and command.workspace_id == "ws-1"
        assert [s.name for s in command.steps] == ["build", "test"]
        save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_failing_step_stops_the_phase_and_skips_the_rest(self) -> None:
        workspace = _Workspace([_exited(2, "error: nope\n")])
        phase = _phase(CommandStep(name="build", run="make"), CommandStep(name="test", run="t"))

        aggregate, _, report, _ = await _run(workspace, phase)

        assert len(workspace.calls) == 1
        assert _outcomes(report) == [CommandStepOutcome.FAILED, CommandStepOutcome.SKIPPED]
        assert report.steps[0].exit_code == 2
        assert not aggregate.recorded[0].success

    @pytest.mark.asyncio
    async def test_allow_failure_excuses_an_exit_code_and_carries_on(self) -> None:
        workspace = _Workspace([_exited(1), _exited(0)])
        phase = _phase(
            CommandStep(name="lint", run="lint", allow_failure=True),
            CommandStep(name="build", run="make"),
        )

        _, _, report, _ = await _run(workspace, phase)

        assert _outcomes(report) == [CommandStepOutcome.FAILED, CommandStepOutcome.PASSED]
        assert report.success

    @pytest.mark.asyncio
    async def test_allow_failure_excuses_its_own_timeout(self) -> None:
        workspace = _Workspace([_ended(CommandTerminal.TIMED_OUT), _exited(0)])
        phase = _phase(
            CommandStep(name="slow", run="sleep 9", timeout_seconds=5, allow_failure=True),
            CommandStep(name="build", run="make"),
        )

        _, _, report, _ = await _run(workspace, phase)

        assert report.success and not report.timed_out
        assert workspace.calls[0].timeout_seconds == 5

    @pytest.mark.asyncio
    async def test_a_step_gets_only_what_remains_of_the_phase_deadline(self) -> None:
        clock = _Clock()
        workspace = _Workspace([_exited(0), _exited(0)], clock=clock, spends=50)
        phase = _phase(
            CommandStep(name="a", run="a"),
            CommandStep(name="b", run="b", timeout_seconds=500),
            timeout=100,
        )

        await _run(workspace, phase, clock=clock)

        assert [c.timeout_seconds for c in workspace.calls] == [100, 50]

    @pytest.mark.asyncio
    async def test_the_phase_deadline_is_never_excused_by_allow_failure(self) -> None:
        workspace = _Workspace([_ended(CommandTerminal.TIMED_OUT)])
        phase = _phase(
            CommandStep(name="a", run="a", allow_failure=True),
            CommandStep(name="b", run="b"),
        )

        aggregate, _, report, _ = await _run(workspace, phase)

        assert report.timed_out and not report.success
        assert _outcomes(report) == [CommandStepOutcome.TIMED_OUT, CommandStepOutcome.SKIPPED]
        assert aggregate.recorded[0].timed_out

    @pytest.mark.asyncio
    async def test_no_budget_left_skips_the_step_unstarted_and_times_the_phase_out(self) -> None:
        clock = _Clock()
        workspace = _Workspace([_exited(0)], clock=clock, spends=100)
        phase = _phase(
            CommandStep(name="a", run="a", allow_failure=True),
            CommandStep(name="b", run="b"),
            timeout=100,
        )

        _, _, report, _ = await _run(workspace, phase, clock=clock)

        assert len(workspace.calls) == 1
        assert _outcomes(report) == [CommandStepOutcome.PASSED, CommandStepOutcome.SKIPPED]
        assert report.timed_out and not report.success

    @pytest.mark.asyncio
    async def test_a_step_that_could_not_start_is_never_excused(self) -> None:
        workspace = _Workspace([_ended(CommandTerminal.FAILED_TO_START)])
        phase = _phase(
            CommandStep(name="a", run="a", allow_failure=True), CommandStep(name="b", run="b")
        )

        _, _, report, _ = await _run(workspace, phase)

        assert _outcomes(report) == [CommandStepOutcome.FAILED_TO_START, CommandStepOutcome.SKIPPED]
        assert not report.success

    @pytest.mark.asyncio
    async def test_the_report_is_written_first_and_a_silent_step_gets_no_log(self) -> None:
        workspace = _Workspace([_exited(0, "hello\n"), _exited(0)])
        phase = _phase(
            CommandStep(name="loud", run="echo hello"), CommandStep(name="quiet", run="true")
        )

        await _run(workspace, phase)

        paths = [path for path, _ in workspace.files]
        assert paths == [COMMANDS_REPORT_PATH, "artifacts/output/commands/loud.log"]
        written = json.loads(workspace.files[0][1])
        assert written["steps"][0]["tail"] == "hello\n" and written["tails_lost"] is False
        assert workspace.files[1][1] == b"hello\n"

    @pytest.mark.asyncio
    async def test_a_cancel_mid_step_interrupts_it_skips_the_rest_and_records_nothing(self) -> None:
        signals = [None, None, MagicMock(signal_type="cancel", reason="stop it")]

        async def check_signal(_execution_id: str) -> object:
            return signals.pop(0) if signals else None

        from syn_shared.control import ControlSignalType

        signals[2].signal_type = ControlSignalType.CANCEL
        controller = MagicMock()
        controller.check_signal = check_signal
        workspace = _Workspace([None])
        phase = _phase(CommandStep(name="a", run="sleep 99"), CommandStep(name="b", run="b"))

        aggregate, save, report, cancelled = await _run(workspace, phase, controller=controller)

        assert cancelled == "stop it"
        assert workspace.interrupted.is_set()
        assert _outcomes(report) == [CommandStepOutcome.INTERRUPTED, CommandStepOutcome.SKIPPED]
        assert aggregate.recorded == []
        save.assert_not_awaited()
        assert workspace.files[0][0] == COMMANDS_REPORT_PATH

    @pytest.mark.asyncio
    async def test_a_cancel_before_a_step_starts_it_never(self) -> None:
        from syn_shared.control import ControlSignalType

        controller = MagicMock()
        controller.check_signal = AsyncMock(
            return_value=MagicMock(signal_type=ControlSignalType.CANCEL, reason=None)
        )
        workspace = _Workspace([])
        phase = _phase(CommandStep(name="a", run="a"))

        _, _, report, cancelled = await _run(workspace, phase, controller=controller)

        assert workspace.calls == []
        assert cancelled == "Cancelled by user"
        assert _outcomes(report) == [CommandStepOutcome.SKIPPED]


@pytest.mark.unit
class TestCommandsReportFromRecord:
    def test_a_lost_workspace_keeps_the_verdict_and_says_its_tails_are_gone(self) -> None:
        from syn_domain.contexts.orchestration._shared.CommandStepValueObjects import (
            CommandStepResult,
        )

        report = CommandsReport.from_record(
            "build",
            success=False,
            timed_out=False,
            steps=[CommandStepResult(name="a", outcome=CommandStepOutcome.FAILED, exit_code=3)],
        )

        assert report.tails_lost
        assert [path for path, _ in report.files()] == [COMMANDS_REPORT_PATH]
        assert json.loads(report.files()[0][1])["steps"][0]["exit_code"] == 3
