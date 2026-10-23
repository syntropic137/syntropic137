"""The refusal policy for a phase's output files, through to the replayed execution (#1913).

The provider refuses some entries rather than read them: a link, a special
file, one past a read limit. A refused FILE is named and recorded on
`ArtifactsCollectedForPhase`, and the rest of the output is collected; a walk
that stopped early cannot say what it missed, so it fails the collection. A
refusal is never collected as an empty file and never silently dropped.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from event_sourcing import (
    DomainEvent,
    EventEnvelope,
    EventMetadata,
    GenericDomainEvent,
    resolve_event_type,
)
from pydantic import ValidationError

from syn_domain.contexts.artifacts._shared.value_objects import UNREPORTED_AGENT
from syn_domain.contexts.orchestration._shared.file_transfer import (
    FileRefusal,
    FilesRefusedError,
)
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    StartExecutionCommand,
    StartPhaseCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
    UnfinishedPhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.ArtifactCollectionHandler import (
    ArtifactCollectionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.output_refusals import (
    OutputCollectionIncompleteError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_workspace import (
    PhaseWorkspace,
)

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
        ArtifactAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        ArtifactRepository,
    )

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

EXECUTION = "exec-1913"
WORKFLOW = "wf-1913"
PHASE = "phase-1913"
REPORT = ("artifacts/output/report.md", b"# Verdict\n\nAll good.")
LINK = FileRefusal(path="artifacts/output/secrets.md", reason="escaping_symlink")
SHARED = FileRefusal(path="artifacts/output/z-shared.md", reason="hard_link")


class _RefusingWorkspace:
    """A workspace whose provider read REPORT and refused ``refused``."""

    def __init__(self, refused: tuple[FileRefusal, ...]) -> None:
        self.refused = refused

    async def inject_files(self, files: list[tuple[str, bytes]]) -> None:
        return None

    async def collect_files(self, patterns: list[str]) -> list[tuple[str, bytes]]:
        raise FilesRefusedError((REPORT,), self.refused)


class _Repo:
    def __init__(self) -> None:
        self.saved: list[ArtifactAggregate] = []

    async def save(self, aggregate: ArtifactAggregate) -> None:
        self.saved.append(aggregate)

    async def get_by_id(self, artifact_id: str) -> None:
        return None


async def _collect(workspace: _RefusingWorkspace, repo: _Repo) -> WorkflowExecutionAggregate:
    handler = ArtifactCollectionHandler(ArtifactCollector(repo, None, None))
    result = await handler.handle(
        todo=TodoItem(execution_id=EXECUTION, action=TodoAction.COLLECT_ARTIFACTS, phase_id=PHASE),
        workspace=cast("ManagedWorkspace", workspace),
        workflow_id=WORKFLOW,
        session_id="sess-1913",
        phase_name="Verify",
        output_artifact_types=("markdown",),
        agent=UNREPORTED_AGENT,
    )
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=EXECUTION,
            workflow_id=WORKFLOW,
            workflow_name="Refusals",
            total_phases=1,
            inputs={},
        )
    )
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=EXECUTION,
            workflow_id=WORKFLOW,
            phase_id=PHASE,
            phase_name="Verify",
            phase_order=1,
            session_id="sess-1913",
        )
    )
    aggregate.artifacts_collected(result.command)
    return _replayed(aggregate)


def _as_stored(metadata: EventMetadata, payload: str) -> DomainEvent:
    event_type = metadata.event_type or ""
    concrete = resolve_event_type(event_type)
    if concrete is not None:
        try:
            return concrete.model_validate_json(payload)
        except ValidationError:
            pass
    return GenericDomainEvent(event_type=event_type, **json.loads(payload))


def _replayed(aggregate: WorkflowExecutionAggregate) -> WorkflowExecutionAggregate:
    """``aggregate`` rebuilt from the JSON of its events, as the store would hand them back."""
    envelopes: list[EventEnvelope[DomainEvent]] = []
    for envelope in aggregate.get_uncommitted_events():
        metadata = envelope.metadata.model_copy(update={"event_type": envelope.event.event_type})
        payload = json.dumps(envelope.event.model_dump(mode="json"))
        envelopes.append(EventEnvelope(event=_as_stored(metadata, payload), metadata=metadata))
    fresh = WorkflowExecutionAggregate()
    fresh.rehydrate(envelopes)
    return fresh


async def test_refused_files_are_recorded_on_the_execution_and_the_rest_collected() -> None:
    repo = _Repo()

    replayed = await _collect(_RefusingWorkspace((LINK, SHARED)), repo)

    assert replayed.refused_files_for(PHASE) == (LINK, SHARED)
    # The file that was read is stored, byte for byte; no refused one is.
    assert len(repo.saved) == 1
    assert repo.saved[0].content == REPORT[1].decode()


async def test_a_walk_that_stopped_fails_the_collection_with_its_refusals() -> None:
    stopped = FileRefusal(path="artifacts/output/many/10001", reason="entry_limit_exceeded")

    with pytest.raises(OutputCollectionIncompleteError) as raised:
        await _collect(_RefusingWorkspace((LINK, stopped)), _Repo())

    assert raised.value.refused == (LINK, stopped)


async def test_an_execution_with_nothing_refused_records_no_refusals() -> None:
    class _Clean(_RefusingWorkspace):
        async def collect_files(self, patterns: list[str]) -> list[tuple[str, bytes]]:
            return [REPORT]

    replayed = await _collect(_Clean(()), _Repo())

    assert replayed.refused_files_for(PHASE) == ()


def _running() -> WorkflowExecutionAggregate:
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=EXECUTION,
            workflow_id=WORKFLOW,
            workflow_name="Refusals",
            total_phases=1,
            inputs={},
        )
    )
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=EXECUTION,
            workflow_id=WORKFLOW,
            phase_id=PHASE,
            phase_name="Verify",
            phase_order=1,
            session_id="sess-1913",
        )
    )
    return aggregate


async def _keep_unfinished(
    workspace: _RefusingWorkspace, repo: _Repo
) -> tuple[list[str], WorkflowExecutionAggregate, MagicMock]:
    """The unfinished-phase path as the processor drives it, then the execution replayed."""
    runtime = MagicMock()
    runtime.agent_for.return_value = UNREPORTED_AGENT
    journal = MagicMock()
    journal.append = AsyncMock()
    workspaces = PhaseWorkspace(
        session_repository=MagicMock(),
        workspace_service=MagicMock(),
        artifact_repository=cast("ArtifactRepository", repo),
        artifact_content_storage=None,
        artifact_query=None,
        observability_writer=None,
        prompt_builder=AsyncMock(),
        command_builder=MagicMock(),
        claude_plugin_materializer=None,
        skill_materializer=None,
        runtime=runtime,
        journal=journal,
        inputs={},
    )
    aggregate = _running()
    kept = await workspaces.keep_unfinished_output(
        TodoItem(execution_id=EXECUTION, action=TodoAction.RUN_AGENT, phase_id=PHASE),
        ExecutablePhase(
            phase_id=PHASE, name="Verify", order=1, output_artifact_types=("markdown",)
        ),
        workspace=cast("ManagedWorkspace", workspace),
        last_agent_message=None,
        outcome=UnfinishedPhase.FAILED,
        aggregate=aggregate,
    )
    return kept, _replayed(aggregate), journal


async def test_an_unfinished_phase_keeps_what_was_read_and_records_every_refusal() -> None:
    repo = _Repo()

    kept, replayed, journal = await _keep_unfinished(_RefusingWorkspace((LINK, SHARED)), repo)

    assert len(kept) == 1
    assert [a.content for a in repo.saved] == [REPORT[1].decode()]
    assert replayed.refused_files_for(PHASE) == (LINK, SHARED)
    journal.append.assert_awaited()


async def test_an_unfinished_phase_whose_walk_stopped_records_why() -> None:
    stopped = FileRefusal(path="artifacts/output/many/10001", reason="entry_limit_exceeded")

    kept, replayed, _ = await _keep_unfinished(_RefusingWorkspace((LINK, stopped)), _Repo())

    assert kept == []
    assert replayed.refused_files_for(PHASE) == (LINK, stopped)
