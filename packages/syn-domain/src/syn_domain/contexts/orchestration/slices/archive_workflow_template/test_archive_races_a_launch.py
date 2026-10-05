"""An archive cannot win against an execution the read model has not seen (#1588).

The archive guard used to ask the execution projection, which lags the store:
an execution that had started but was not yet projected was invisible, and
prune archived its template under it. These tests drive the handler with an
execution projection that is ALWAYS empty, so every refusal below comes from
the template's stream and the execution aggregates, never from a read model.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from event_sourcing import ConcurrencyConflictError

from syn_domain.contexts.orchestration._shared.template_launch import (
    LAUNCH_GRACE,
    TemplateArchivedError,
    TemplateLaunches,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.ArchiveWorkflowTemplateCommand import (
    ArchiveWorkflowTemplateCommand,
)
from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
    CreateWorkflowTemplateCommand,
)
from syn_domain.contexts.orchestration.slices.archive_workflow_template.ArchiveWorkflowTemplateHandler import (
    ArchiveWorkflowTemplateHandler,
)

WF = "wf-race"


class VersionedRepository:
    """A template store that refuses a save made against a stale version, as the event store does."""

    def __init__(self, template: WorkflowTemplateAggregate) -> None:
        self._committed = template
        self._loaded_at: dict[int, int] = {}

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
        loaded = copy.deepcopy(self._committed)
        self._loaded_at[id(loaded)] = loaded.version
        return loaded

    async def save(self, aggregate: WorkflowTemplateAggregate) -> None:
        expected = self._loaded_at[id(aggregate)]
        if expected != self._committed.version:
            raise ConcurrencyConflictError(expected, self._committed.version)
        aggregate.mark_events_as_committed()
        self._committed = copy.deepcopy(aggregate)
        self._loaded_at[id(aggregate)] = aggregate.version

    def current(self) -> WorkflowTemplateAggregate:
        return self._committed


@dataclass(frozen=True)
class _Execution:
    status: str
    workflow_execution_id: str = ""


class Executions:
    """Execution streams by id. ``on_read`` runs while the archive is mid-decision."""

    def __init__(self, streams: dict[str, str] | None = None) -> None:
        self.streams = streams or {}
        self.on_read: list[object] = []

    async def get_by_id(self, aggregate_id: str) -> _Execution | None:
        for hook in self.on_read:
            await hook()  # type: ignore[operator]
        self.on_read.clear()
        status = self.streams.get(aggregate_id)
        return None if status is None else _Execution(status=status)


class NeverProjected:
    """The execution projection before the subscription has caught up: empty."""

    async def get_by_workflow_id(self, workflow_id: str) -> list[_Execution]:
        return []


def _template() -> WorkflowTemplateAggregate:
    aggregate = WorkflowTemplateAggregate()
    aggregate._handle_command(
        CreateWorkflowTemplateCommand(
            aggregate_id=WF,
            name="Race",
            workflow_type=WorkflowType.RESEARCH,
            classification=WorkflowClassification.SIMPLE,
            repository_url="https://github.com/test/repo",
            repository_ref="main",
            phases=[PhaseDefinition(phase_id="p1", name="P1", order=1)],
        )
    )
    aggregate.mark_events_as_committed()
    return aggregate


def _archive(repo: VersionedRepository, executions: Executions) -> ArchiveWorkflowTemplateHandler:
    return ArchiveWorkflowTemplateHandler(
        repository=repo,  # type: ignore[arg-type]
        execution_projection=NeverProjected(),
        executions=executions,
    )


async def _launched(*execution_ids: str) -> VersionedRepository:
    repo = VersionedRepository(_template())
    for execution_id in execution_ids:
        await TemplateLaunches(repo).record(WF, execution_id)  # type: ignore[arg-type]
    return repo


@pytest.mark.unit
class TestArchiveAgainstUnprojectedExecutions:
    async def test_a_running_execution_not_yet_projected_blocks_the_archive(self) -> None:
        repo = await _launched("exec-1")
        result = await _archive(repo, Executions({"exec-1": "running"})).handle(
            ArchiveWorkflowTemplateCommand(workflow_id=WF)
        )
        assert result is not None and not result.success
        assert "1 active execution" in (result.error or "")
        assert not repo.current().is_archived

    async def test_a_launch_whose_execution_stream_is_not_written_yet_blocks_the_archive(
        self,
    ) -> None:
        repo = await _launched("exec-1")
        result = await _archive(repo, Executions()).handle(
            ArchiveWorkflowTemplateCommand(workflow_id=WF)
        )
        assert result is not None and not result.success
        assert not repo.current().is_archived

    async def test_finished_executions_do_not_block(self) -> None:
        repo = await _launched("exec-1", "exec-2")
        executions = Executions({"exec-1": "completed", "exec-2": "failed"})
        result = await _archive(repo, executions).handle(
            ArchiveWorkflowTemplateCommand(workflow_id=WF)
        )
        assert result is not None and result.success
        assert repo.current().is_archived

    async def test_a_launch_that_never_started_stops_blocking_after_the_grace(self) -> None:
        repo = await _launched("exec-1")
        repo.current()._launches["exec-1"] = datetime.now(UTC) - LAUNCH_GRACE * 2
        result = await _archive(repo, Executions()).handle(
            ArchiveWorkflowTemplateCommand(workflow_id=WF)
        )
        assert result is not None and result.success


@pytest.mark.unit
class TestLaunchAndArchiveShareOneStream:
    async def test_a_launch_recorded_mid_archive_makes_the_archive_conflict(self) -> None:
        repo = await _launched("exec-done")
        executions = Executions({"exec-done": "completed"})

        async def a_launch_lands() -> None:
            await TemplateLaunches(repo).record(WF, "exec-new")  # type: ignore[arg-type]

        executions.on_read.append(a_launch_lands)
        result = await _archive(repo, executions).handle(
            ArchiveWorkflowTemplateCommand(workflow_id=WF)
        )

        assert result is not None and not result.success
        assert "launched while archiving" in (result.error or "")
        assert not repo.current().is_archived
        assert "exec-new" in repo.current().launches

    async def test_a_launch_after_the_archive_is_refused(self) -> None:
        repo = await _launched()
        result = await _archive(repo, Executions()).handle(
            ArchiveWorkflowTemplateCommand(workflow_id=WF)
        )
        assert result is not None and result.success
        with pytest.raises(TemplateArchivedError, match="archived"):
            await TemplateLaunches(repo).record(WF, "exec-late")  # type: ignore[arg-type]

    async def test_recording_the_same_launch_twice_records_it_once(self) -> None:
        repo = await _launched("exec-1")
        version = repo.current().version
        await TemplateLaunches(repo).record(WF, "exec-1")  # type: ignore[arg-type]
        assert repo.current().version == version


@pytest.mark.unit
class TestTheExecuteHandlerRecordsTheLaunch:
    """The consumer of ``TemplateLaunches``: a launch reaches the template's stream."""

    @staticmethod
    def _handler(repo: VersionedRepository) -> tuple[object, AsyncMock]:
        from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
            ExecuteWorkflowHandler,
        )

        processor = AsyncMock()
        handler = ExecuteWorkflowHandler(
            processor=processor,
            workflow_repository=repo,  # type: ignore[arg-type]
            launches=TemplateLaunches(repo),  # type: ignore[arg-type]
        )
        return handler, processor.run

    @staticmethod
    def _command() -> object:
        from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
            ExecuteWorkflowCommand,
        )

        return ExecuteWorkflowCommand(aggregate_id=WF, execution_id="exec-abc123")

    async def test_the_launch_is_on_the_template_stream_before_the_run(self) -> None:
        repo = await _launched()
        handler, run = self._handler(repo)

        async def run_sees_the_launch(**_: object) -> None:
            assert "exec-abc123" in repo.current().launches

        run.side_effect = run_sees_the_launch
        await handler.handle(self._command())  # type: ignore[attr-defined]
        run.assert_awaited_once()

    async def test_an_archived_template_never_reaches_the_processor(self) -> None:
        repo = await _launched()
        await _archive(repo, Executions()).handle(ArchiveWorkflowTemplateCommand(workflow_id=WF))
        handler, run = self._handler(repo)
        with pytest.raises(TemplateArchivedError):
            await handler.handle(self._command())  # type: ignore[attr-defined]
        run.assert_not_awaited()
