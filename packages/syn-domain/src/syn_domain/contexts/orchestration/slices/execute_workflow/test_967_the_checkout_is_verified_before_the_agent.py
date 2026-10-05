"""A pinned workspace is read back and verified before its agent runs, and recorded (#967).

The setup script checking a repository out at its pin and exiting 0 says the
lines ran, not where HEAD ended up. These drive `WorkspaceProvisionHandler`
against a workspace that ANSWERS `git rev-parse HEAD` per repository, and then
read the outcome where it is consumed: the aggregate rebuilt from the stored
JSON of what provisioning recorded, and the run's failure record.

Every sha here is one nothing else in the system produces, so finding it on the
replayed aggregate can only mean it travelled from the workspace's answer.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from event_sourcing import (
    DomainEvent,
    EventEnvelope,
    EventMetadata,
    GenericDomainEvent,
    resolve_event_type,
)
from pydantic import ValidationError

from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    SourceCommit,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    CheckoutMismatch,
    CheckoutMismatchError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    ProvisionResult,
    WorkspaceProvisionHandler,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

EXECUTION = "exec-967-checkout"
WORKFLOW = "wf-967"
PHASE = "implement"

APP = "syntropic137/eval-app"
LIB = "syntropic137/eval-lib"
APP_URL = f"https://github.com/{APP}"
LIB_URL = f"https://github.com/{LIB}"
APP_PIN = "967a0000000000000000000000000000000000a1"
LIB_PIN = "967b0000000000000000000000000000000000b2"
#: Where a provisioning that did not honour the pin left the app instead.
ELSEWHERE = "0ff00000000000000000000000000000000000c3"

PINS = [SourceCommit(repository=APP, sha=APP_PIN), SourceCommit(repository=LIB, sha=LIB_PIN)]


def _phase() -> ExecutablePhase:
    return ExecutablePhase(
        phase_id=PHASE,
        name="Make the change",
        order=1,
        agent_config=AgentConfiguration(),
        prompt_template="Do the task",
        output_artifact_types=(),
    )


def _workspace_at(heads: Mapping[str, str]) -> MagicMock:
    """A workspace service whose setup succeeds and whose repos stand at ``heads``.

    ``heads`` maps a clone's directory to its HEAD. `git -C <dir> rev-parse HEAD`
    is answered from it; any other command succeeds and says nothing.
    """

    async def execute(command: list[str], **_: object) -> ExecutionResult:
        stdout = ""
        if command[-2:] == ["rev-parse", "HEAD"]:
            stdout = heads[command[command.index("-C") + 1]] + "\n"
        return ExecutionResult(exit_code=0, success=True, duration_ms=1.0, stdout=stdout)

    workspace = AsyncMock()
    workspace.proxy_url = "http://envoy:10000"
    workspace.workspace_id = "ws-967"
    workspace.run_setup_phase = AsyncMock(
        return_value=ExecutionResult(exit_code=0, success=True, duration_ms=1.0)
    )
    workspace.execute = AsyncMock(side_effect=execute)
    workspace_cm = AsyncMock()
    workspace_cm.__aenter__ = AsyncMock(return_value=workspace)
    workspace_cm.__aexit__ = AsyncMock(return_value=False)
    service = MagicMock()
    service.create_workspace.return_value = workspace_cm
    return service


async def _provision(heads: Mapping[str, str], repos: list[str]) -> ProvisionResult:
    handler = WorkspaceProvisionHandler(
        workspace_service=_workspace_at(heads),
        prompt_builder=AsyncMock(return_value="Do the task"),
        command_builder=MagicMock(return_value=["claude", "--print", "Do the task"]),
    )
    with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as secrets:
        secrets.create = AsyncMock(return_value=MagicMock())
        return await handler.handle(
            todo=TodoItem(
                execution_id=EXECUTION, action=TodoAction.PROVISION_WORKSPACE, phase_id=PHASE
            ),
            phase=_phase(),
            workflow_id=WORKFLOW,
            session_id="sess-967",
            repos=repos,
            pinned_commits=PINS,
        )


def _as_stored(metadata: EventMetadata, payload: str) -> DomainEvent:
    """An event as the store deserialises it: typed, or generic if that fails (ADR-023)."""
    event_type = metadata.event_type or ""
    concrete = resolve_event_type(event_type)
    if concrete is not None:
        try:
            return concrete.model_validate_json(payload)
        except ValidationError:
            pass
    return GenericDomainEvent(event_type=event_type, **json.loads(payload))


def _replayed(
    aggregate: WorkflowExecutionAggregate, *, drop: str | None = None
) -> WorkflowExecutionAggregate:
    """``aggregate`` rebuilt from the JSON of its events, ``drop`` removed from each."""
    stored: list[tuple[EventMetadata, str]] = []
    for envelope in aggregate.get_uncommitted_events():
        payload = envelope.event.model_dump(mode="json")
        payload.pop(drop or "", None)
        metadata = envelope.metadata.model_copy(update={"event_type": envelope.event.event_type})
        stored.append((metadata, json.dumps(payload)))
    fresh = WorkflowExecutionAggregate()
    fresh.rehydrate(
        [EventEnvelope(event=_as_stored(m, p), metadata=m) for m, p in stored],
    )
    return fresh


def _started_and_provisioned(result: ProvisionResult) -> WorkflowExecutionAggregate:
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=EXECUTION,
            workflow_id=WORKFLOW,
            workflow_name="Eval run",
            total_phases=1,
            inputs={},
            source_commits=PINS,
        )
    )
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=EXECUTION,
            workflow_id=WORKFLOW,
            phase_id=PHASE,
            phase_name="Make the change",
            phase_order=1,
            session_id="sess-967",
        )
    )
    aggregate.provision_workspace_completed(result.command)
    return aggregate


async def test_the_pinned_checkout_is_recorded_and_survives_replay() -> None:
    result = await _provision({"/workspace/repos/eval-app": APP_PIN}, [APP_URL])

    replayed = _replayed(_started_and_provisioned(result))

    assert replayed.starting_checkout == [SourceCommit(repository=APP, sha=APP_PIN)]


async def test_every_repository_of_a_two_repo_baseline_is_verified_and_recorded() -> None:
    heads = {"/workspace/repos/eval-app": APP_PIN, "/workspace/repos/eval-lib": LIB_PIN}
    result = await _provision(heads, [APP_URL, LIB_URL])

    replayed = _replayed(_started_and_provisioned(result))

    assert replayed.starting_checkout == PINS


async def test_a_mismatch_in_either_repository_refuses_the_workspace_by_name() -> None:
    heads = {"/workspace/repos/eval-app": ELSEWHERE, "/workspace/repos/eval-lib": LIB_PIN}

    with pytest.raises(CheckoutMismatchError) as refused:
        await _provision(heads, [APP_URL, LIB_URL])

    assert refused.value.mismatches == (CheckoutMismatch(APP, APP_PIN, ELSEWHERE),)


async def test_a_mismatch_fails_the_run_before_any_agent_runs() -> None:
    """The refusal reaches the run's failure record, and no agent is launched."""
    from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
    from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
        WorkflowExecutionProcessor,
    )
    from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
        ExecutionTodoProjection,
    )

    agent = AsyncMock()
    processor = WorkflowExecutionProcessor(
        execution_repository=AsyncMock(),
        session_repository=AsyncMock(),
        workspace_service=_workspace_at({"/workspace/repos/eval-app": ELSEWHERE}),
        artifact_repository=AsyncMock(),
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=AsyncMock(return_value="Do the task"),
        command_builder=MagicMock(return_value=["claude", "--print", "Do the task"]),
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
        agent_handler=agent,
    )
    processor._journal._repository.save = AsyncMock()

    with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as secrets:
        secrets.create = AsyncMock(return_value=MagicMock())
        result = await processor.run(
            workflow_id=WORKFLOW,
            workflow_name="Eval run",
            phases=[_phase()],
            inputs={},
            execution_id=EXECUTION,
            repos=[RepositoryRef.parse(APP)],
            source_commits=[SourceCommit(repository=APP, sha=APP_PIN)],
        )

    assert result.status == "failed"
    assert result.error_message is not None
    assert f"{APP} is at {ELSEWHERE}, pinned to {APP_PIN}" in result.error_message
    agent.handle.assert_not_called()


async def test_a_provisioning_recorded_before_the_field_existed_still_replays() -> None:
    result = await _provision({"/workspace/repos/eval-app": APP_PIN}, [APP_URL])

    replayed = _replayed(_started_and_provisioned(result), drop="checked_out_commits")

    assert replayed.starting_checkout == []
    assert replayed.start_pins.source_commits == PINS
