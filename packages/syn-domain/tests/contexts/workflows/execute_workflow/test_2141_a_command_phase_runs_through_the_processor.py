"""#2141: a command Phase runs through the real processor, with no agent (ADR-078).

Drives ``WorkflowExecutionProcessor`` over two command Phases on the memory
workspace backend, whose transport answers each step's ``run`` line from a
script. Asserted at the boundaries: what reached the event store, which steps
the transport was asked to run, what was stored as an artifact, and that no
agent session was ever opened.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from syn_adapters.control.commands import ControlSignal, ControlSignalType
from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.workspace_backends.memory import MemoryEventStreamAdapter
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_domain.contexts.orchestration._shared.command_phase import (
    BoundedCommandResult,
    CommandStep,
    CommandTerminal,
    PhaseKind,
)
from syn_domain.contexts.orchestration._shared.CommandStepValueObjects import CommandStepOutcome
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
    FailureClassification,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.command_report import CommandsReport
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import PhaseRuntime
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
    WorkflowExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.testing.fake_session_repository import FakeSessionRepository

from .test_processor_smoke import (
    FakeExecutionRepository,
    _noop_command_builder,
    _noop_prompt_builder,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from syn_domain.contexts.artifacts import ArtifactAggregate
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )

pytestmark = pytest.mark.unit

_BOUND_SECONDS = 20.0


def _exited(code: int, tail: str = "") -> BoundedCommandResult:
    return BoundedCommandResult(
        terminal=CommandTerminal.EXITED, exit_code=code, duration_ms=10, tail=tail
    )


class _ScriptedSteps(MemoryEventStreamAdapter):
    """Answers a step by its ``run`` line; ``"block"`` waits for a cancel."""

    def __init__(self, answers: dict[str, BoundedCommandResult]) -> None:
        super().__init__()
        self.answers = answers
        self.ran: list[str] = []
        self.blocking = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def run_bounded(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
        tail_bytes: int = 8192,
        withheld: Callable[[], Iterable[str]] | None = None,
    ) -> BoundedCommandResult:
        run = command[-1]
        self.ran.append(run)
        if run == "block":
            self.blocking.set()
            await self.cancelled.wait()
            return BoundedCommandResult(terminal=CommandTerminal.INTERRUPTED, duration_ms=10)
        return self.answers.get(run, _exited(0))

    async def cancel_running(self, handle: IsolationHandle) -> bool:
        self.cancelled.set()
        return True


class _Artifacts:
    def __init__(self) -> None:
        self.saved: list[ArtifactAggregate] = []

    async def save(self, aggregate: ArtifactAggregate) -> None:
        self.saved.append(aggregate)

    async def get_by_id(self, aggregate_id: str) -> None:
        return None


class _CancelWhenAsked:
    def __init__(self) -> None:
        self.pending = False

    async def check_signal(self, execution_id: str) -> ControlSignal | None:
        if not self.pending:
            return None
        return ControlSignal(
            signal_type=ControlSignalType.CANCEL, execution_id=execution_id, reason="stop"
        )


def _phases(*first: CommandStep) -> list[ExecutablePhase]:
    """`build` runs ``first``; `test` runs ``make test`` and shows whether the run went on."""
    return [
        ExecutablePhase(
            phase_id="build",
            name="Build",
            order=1,
            kind=PhaseKind.COMMAND,
            commands=first,
            timeout_seconds=600,
            clone_repos=False,
        ),
        ExecutablePhase(
            phase_id="test",
            name="Test",
            order=2,
            kind=PhaseKind.COMMAND,
            commands=(CommandStep(name="test", run="make test"),),
            timeout_seconds=600,
            clone_repos=False,
        ),
    ]


class _Run:
    def __init__(self, steps: _ScriptedSteps, controller: _CancelWhenAsked | None = None) -> None:
        self.steps = steps
        self.sessions = FakeSessionRepository()
        self.artifacts = _Artifacts()
        workspace_service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)
        workspace_service._event_stream = steps  # pyright: ignore[reportPrivateUsage]
        self.processor = WorkflowExecutionProcessor(
            execution_repository=FakeExecutionRepository(),
            session_repository=self.sessions,
            workspace_service=workspace_service,
            artifact_repository=self.artifacts,
            artifact_content_storage=None,
            artifact_query=None,
            conversation_storage=None,
            observability_writer=None,
            controller=controller,  # pyright: ignore[reportArgumentType]
            prompt_builder=_noop_prompt_builder,
            command_builder=_noop_command_builder,
            todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
            agent_handler=None,
        )
        self.events: list[object] = []
        repository = self.processor._journal._repository  # pyright: ignore[reportPrivateUsage]
        original_save = repository.save

        async def capturing_save(aggregate: WorkflowExecutionAggregate) -> None:
            self.events.extend(e.event for e in aggregate.get_uncommitted_events())
            await original_save(aggregate)

        repository.save = capturing_save  # pyright: ignore[reportAttributeAccessIssue]

    def start(self, phases: list[ExecutablePhase]) -> asyncio.Task[WorkflowExecutionResult]:
        return asyncio.create_task(
            self.processor.run(
                workflow_id="wf-2141",
                workflow_name="Command phases",
                phases=phases,
                inputs={},
                execution_id="exec-2141",
            )
        )

    async def __call__(self, phases: list[ExecutablePhase]) -> WorkflowExecutionResult:
        async with asyncio.timeout(_BOUND_SECONDS):
            return await self.start(phases)

    def named(self, name: str) -> list[object]:
        return [e for e in self.events if type(e).__name__ == name]

    def report_of(self, phase_id: str) -> CommandsReport:
        [primary] = [
            a for a in self.artifacts.saved if a.phase_id == phase_id and a.is_primary_deliverable
        ]
        assert primary.source_path == "artifacts/output/commands.json"
        return CommandsReport.model_validate_json(primary.content)


@pytest.mark.anyio
async def test_every_step_runs_and_the_run_completes_without_an_agent() -> None:
    steps = _ScriptedSteps({"make": _exited(0, "built\n")})
    run = _Run(steps)

    result = await run(_phases(CommandStep(name="build", run="make")))

    assert result.status == "completed", result.error_message
    assert steps.ran == ["make", "make test"]
    assert len(run.named("PhaseCommandsCompletedEvent")) == 2
    assert run.named("AgentExecutionCompletedEvent") == []
    assert run.sessions.streams == {}, "a command phase opened an agent session"
    assert result.metrics.total_tokens == 0
    report = run.report_of("build")
    assert report.success and not report.tails_lost
    logs = [a.source_path for a in run.artifacts.saved if a.phase_id == "build"]
    assert "artifacts/output/commands/build.log" in logs


@pytest.mark.anyio
async def test_a_failed_step_fails_the_run_as_a_gate_and_no_later_phase_runs() -> None:
    steps = _ScriptedSteps({"make": _exited(2, "error: nope\n")})
    run = _Run(steps)

    result = await run(_phases(CommandStep(name="build", run="make")))

    assert result.status == "failed"
    assert result.failure_classification is FailureClassification.GATE
    assert "step 'build' exited 2" in (result.error_message or "")
    assert steps.ran == ["make"]
    # The failed build's logs were collected before the run ended.
    assert not run.report_of("build").success


@pytest.mark.anyio
async def test_allow_failure_lets_the_run_go_on() -> None:
    steps = _ScriptedSteps({"lint": _exited(1)})
    run = _Run(steps)

    result = await run(
        _phases(
            CommandStep(name="lint", run="lint", allow_failure=True),
            CommandStep(name="build", run="make"),
        )
    )

    assert result.status == "completed", result.error_message
    assert steps.ran == ["lint", "make", "make test"]


@pytest.mark.anyio
async def test_a_step_timeout_fails_the_run_as_a_gate() -> None:
    timed_out = BoundedCommandResult(terminal=CommandTerminal.TIMED_OUT, duration_ms=5000)
    steps = _ScriptedSteps({"make": timed_out})
    run = _Run(steps)

    result = await run(_phases(CommandStep(name="build", run="make", timeout_seconds=5)))

    assert result.status == "failed"
    assert result.failure_classification is FailureClassification.GATE
    assert "timed out" in (result.error_message or "")
    assert steps.ran == ["make"]


@pytest.mark.anyio
async def test_a_cancel_mid_step_cancels_the_run_and_keeps_the_report() -> None:
    steps = _ScriptedSteps({})
    controller = _CancelWhenAsked()
    run = _Run(steps, controller)

    task = run.start(_phases(CommandStep(name="slow", run="block"), CommandStep(name="b", run="b")))
    async with asyncio.timeout(_BOUND_SECONDS):
        await steps.blocking.wait()
        controller.pending = True
        result = await task

    assert result.status == "cancelled"
    assert steps.ran == ["block"]
    assert len(run.named("ExecutionCancelledEvent")) == 1
    assert run.named("PhaseCommandsCompletedEvent") == []
    report = run.report_of("build")
    assert [s.outcome for s in report.steps] == [
        CommandStepOutcome.INTERRUPTED,
        CommandStepOutcome.SKIPPED,
    ]


@pytest.mark.anyio
async def test_a_restart_that_lost_the_workspace_collects_the_recorded_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D6: after `PhaseCommandsCompleted`, collection finds no workspace."""
    steps = _ScriptedSteps({"make": _exited(2, "error: nope\n")})
    run = _Run(steps)
    original = PhaseRuntime.workspace_for

    def lost_after_the_steps(self: PhaseRuntime, phase_id: str) -> object:
        if run.named("PhaseCommandsCompletedEvent"):
            return None
        return original(self, phase_id)

    monkeypatch.setattr(PhaseRuntime, "workspace_for", lost_after_the_steps)

    result = await run(_phases(CommandStep(name="build", run="make")))

    assert result.status == "failed"
    assert result.failure_classification is FailureClassification.GATE
    report = run.report_of("build")
    assert report.tails_lost
    assert [(s.exit_code, s.tail) for s in report.steps] == [(2, "")]
