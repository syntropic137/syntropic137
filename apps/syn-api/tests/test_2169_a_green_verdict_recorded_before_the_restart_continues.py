"""A green command verdict recorded before a restart continues the run (#2169, ADR-078 D6).

The stranded command Phase `build` passed, and the stream says so. Boot
reconciliation collects it from the event and hands the run back to a REAL
`WorkflowExecutionProcessor` over the same event store, which drains the to-do
list from the stream alone: the next Phase is dispatched, or, when `build` was
the last one, the run completes. Neither ends as `OrphanedByRestart`.

The workspace is a double whose setup fails, so a dispatched `review` is seen as
its `PhaseStarted` and a provision attempt, and nothing runs an agent.
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.repositories import EventStoreExecutionEventStream, RepositoryAdapter
from syn_api.services import reconciliation
from syn_api.services.reconciliation import CleanupResult, reconcile_orphaned_executions
from syn_domain.contexts.orchestration._shared.command_phase import CommandStep, PhaseKind
from syn_domain.contexts.orchestration._shared.CommandStepValueObjects import (
    CommandStepOutcome,
    CommandStepResult,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
    phase_definitions_of,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    RecordPhaseCommandsCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.command_report import (
    COMMANDS_REPORT_PATH,
    CommandsReport,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.testing.stored_replay import stored_envelopes

if TYPE_CHECKING:
    from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
        ArtifactAggregate,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_REAPED = CleanupResult(fully_reaped=True)
_CUTOFF = datetime(2030, 1, 1, tzinfo=UTC)
EXECUTION_ID = "exec-2169-green"
WORKFLOW_ID = "wf-2169-green"

BUILD = ExecutablePhase(
    phase_id="build",
    name="build",
    order=1,
    kind=PhaseKind.COMMAND,
    commands=(CommandStep(name="cargo-build", run="cargo build"),),
)
REVIEW = ExecutablePhase(phase_id="review", name="review", order=2, prompt_template="review it")
PASSED = CommandStepResult(
    name="cargo-build", outcome=CommandStepOutcome.PASSED, exit_code=0, duration_ms=1500
)


class _Summary:
    workflow_execution_id = EXECUTION_ID
    completed_phases = 0
    started_at = datetime(2026, 11, 9, 3, 15, tzinfo=UTC)

    def __init__(self, total_phases: int) -> None:
        self.total_phases = total_phases


class _ArtifactRepository:
    def __init__(self) -> None:
        self.saved: list[ArtifactAggregate] = []

    async def save(self, aggregate: ArtifactAggregate) -> None:
        self.saved.append(aggregate)

    async def save_new(self, aggregate: ArtifactAggregate) -> None:
        await self.save(aggregate)


def _failing_workspace() -> MagicMock:
    workspace_service = MagicMock()
    workspace_service.create_workspace.return_value.__aenter__.return_value.run_setup_phase = (
        AsyncMock(
            return_value=ExecutionResult(
                exit_code=1, success=False, duration_ms=0.0, stderr="setup failed"
            )
        )
    )
    return workspace_service


class _World:
    """One durable event store: the dead process wrote it, the new one reads it."""

    def __init__(self, phases: list[ExecutablePhase]) -> None:
        self.phases = phases
        self.store = MemoryEventStoreClient()
        self.workspace = _failing_workspace()
        self.artifacts = _ArtifactRepository()

    def repository(self) -> RepositoryAdapter[WorkflowExecutionAggregate]:
        return RepositoryAdapter(
            EventStoreRepository(
                self.store,
                WorkflowExecutionAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                "WorkflowExecution",
            )
        )

    async def processor(self) -> WorkflowExecutionProcessor:
        """A fresh processor, built only after the restart."""
        return WorkflowExecutionProcessor(
            execution_repository=self.repository(),
            session_repository=AsyncMock(),
            workspace_service=self.workspace,
            artifact_repository=AsyncMock(),
            artifact_content_storage=None,
            artifact_query=None,
            conversation_storage=None,
            observability_writer=None,
            controller=None,
            prompt_builder=AsyncMock(return_value="test prompt"),
            command_builder=MagicMock(return_value=["claude"]),
            todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),  # type: ignore[arg-type]
            execution_events=EventStoreExecutionEventStream(self.store),
            todo_projection_type=ExecutionTodoProjection,
        )

    async def strand(self) -> None:
        """`build` started and recorded a green verdict; then the process died."""
        aggregate = WorkflowExecutionAggregate()
        aggregate.start_execution(
            StartExecutionCommand(
                execution_id=EXECUTION_ID,
                workflow_id=WORKFLOW_ID,
                workflow_name="gate",
                total_phases=len(self.phases),
                inputs={},
                phase_definitions=phase_definitions_of(self.phases),
                pinned_phases=self.phases,
            )
        )
        aggregate.start_phase(
            StartPhaseCommand(
                execution_id=EXECUTION_ID,
                workflow_id=WORKFLOW_ID,
                phase_id="build",
                phase_name="build",
                phase_order=1,
            )
        )
        aggregate.record_phase_commands(
            RecordPhaseCommandsCommand(
                execution_id=EXECUTION_ID,
                phase_id="build",
                workspace_id="ws-2169",
                success=True,
                steps=[PASSED],
            )
        )
        await self.repository().save_new(aggregate)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        summary = _Summary(len(self.phases))

        class _List:
            async def get_all(self, **_: object) -> list[_Summary]:
                return [summary]

        class _Manager:
            workflow_execution_list = _List()

        async def _no_object_storage() -> None:
            return None

        monkeypatch.setattr("syn_api._wiring.get_projection_mgr", _Manager)
        monkeypatch.setattr(
            "syn_adapters.storage.repositories.get_workflow_execution_repository",
            self.repository,
        )
        monkeypatch.setattr(
            "syn_adapters.storage.repositories.get_artifact_repository", lambda: self.artifacts
        )
        monkeypatch.setattr(
            "syn_adapters.storage.artifact_storage.get_artifact_storage", _no_object_storage
        )
        monkeypatch.setattr("syn_api._wiring.get_execution_processor", self.processor)

    async def events(self) -> list[Any]:
        return [
            e.event
            for e in await stored_envelopes(self.store)
            if e.metadata.aggregate_id == EXECUTION_ID
        ]

    async def named(self, event_type: str) -> list[Any]:
        return [e for e in await self.events() if e.event_type == event_type]

    def stored_report(self) -> CommandsReport:
        reports = [a for a in self.artifacts.saved if a.source_path == COMMANDS_REPORT_PATH]
        assert len(reports) == 1, "the recorded verdict was not stored as commands.json"
        return CommandsReport.model_validate_json(reports[0].content)


async def _restart(world: _World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.install(monkeypatch)
    await reconcile_orphaned_executions(_REAPED, started_before=_CUTOFF)
    continuing = list(reconciliation._CONTINUING)
    assert len(continuing) == 1, "the green run was not handed back to the processor"
    await asyncio.wait_for(asyncio.gather(*continuing), timeout=30)


async def test_a_green_verdict_dispatches_the_next_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World([BUILD, REVIEW])
    await world.strand()

    await _restart(world, monkeypatch)

    report = world.stored_report()
    assert report.tails_lost is True
    assert report.success is True
    completed = await world.named("PhaseCompleted")
    assert [e.phase_id for e in completed][:1] == ["build"]
    started = [e.phase_id for e in await world.named("PhaseStarted")]
    assert started == ["build", "review"], "the next phase was never dispatched"
    world.workspace.create_workspace.assert_called()
    failed = await world.named("WorkflowFailed")
    assert all(f.error_type != "OrphanedByRestart" for f in failed)
    # `review`'s setup fails on purpose, so that is the only failure there is.
    assert [f.failed_phase_id for f in failed] == ["review"]


async def test_a_green_verdict_on_the_last_phase_completes_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World([BUILD])
    await world.strand()

    await _restart(world, monkeypatch)

    assert world.stored_report().tails_lost is True
    assert [e.phase_id for e in await world.named("PhaseCompleted")] == ["build"]
    assert await world.named("WorkflowFailed") == []
    assert len(await world.named("WorkflowCompleted")) == 1
    world.workspace.create_workspace.assert_not_called()
