"""What the STORED record says when provisioning dies mid-command (#1158).

Most assertions here read ``WorkflowExecutionResult.error_message`` after
running the real ``WorkflowExecutionProcessor``, because that field is the
whole of what #1158 is about. The PC-126 assertions read the STORED
``WorkflowFailedEvent`` instead: each save is snapshotted as serialized JSON
and rehydrated, so a structured field dropped anywhere before the store is
missing from what these tests read. The failures it describes cost $0.00 and leave
no agent transcript, so when the container is gone this string is the only
evidence that the execution ever happened. It said::

    Secret-injection setup failed for phase 'Prepare the workspace':
    Cloning into '/workspace/repos/syntropic137'...

which is git reporting progress, not git reporting a failure. The process was
killed while the clone was still running; the one fact that said so - the exit
status - was kept only as a fallback for when stderr came back empty, so in
practice it was never recorded.

Tests elsewhere pin the raised exception (``test_handlers.py``) and the
wording (``test_setup_failure_names_which_setup.py``). These run the far end
instead: five hops sit between the ``raise`` and this field, and a status
dropped at any one of them leaves both ends still looking correct.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration._shared.resolved_skill import ResolvedSkill
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    FailureClassification,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_shared.upstream_failure import UpstreamFailureKind

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        WorkflowExecutionResult,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

#: The phase from the #1158 reproduction.
PHASE_NAME = "Prepare the workspace"

#: What git had printed when the process was killed under it. Nothing here is
#: an error, which is exactly why promoting it cost a wrong diagnosis.
CLONE_PROGRESS = "Cloning into '/workspace/repos/syntropic137'..."

#: 128 + SIGKILL. `docker exec` is a shell for this purpose, so this - not -9 -
#: is the form the setup phase's own failures arrive in.
SIGKILLED = 137


def _phase(*, skills: tuple[ResolvedSkill, ...] = ()) -> ExecutablePhase:
    return ExecutablePhase(
        phase_id="phase-1",
        name=PHASE_NAME,
        order=1,
        description="",
        agent_config=AgentConfiguration(provider="codex"),
        prompt_template="Do the task",
        output_artifact_types=("text",),
        skills=skills,
    )


def _workspace(*, setup: ExecutionResult, command: ExecutionResult | None = None) -> AsyncMock:
    """A workspace whose ADR-024 setup returns `setup` and whose commands return `command`."""
    workspace = AsyncMock()
    workspace.proxy_url = "http://envoy:10000"
    workspace.workspace_id = "ws-1158"
    workspace.run_setup_phase = AsyncMock(return_value=setup)
    workspace.inject_files = AsyncMock()
    if command is not None:
        workspace.execute = AsyncMock(return_value=command)
    return workspace


async def _persisted_error(
    workspace: AsyncMock,
    phase: ExecutablePhase,
    *,
    skill_materializer: AsyncMock | None = None,
) -> str:
    """Run the real processor over `phase` and return what an operator reads."""
    result, _ = await _run(workspace, phase, skill_materializer=skill_materializer)
    assert result.error_message is not None
    return result.error_message


async def _stored_failure(
    workspace: AsyncMock,
    phase: ExecutablePhase,
    *,
    skill_materializer: AsyncMock | None = None,
) -> WorkflowFailedEvent:
    """Run the real processor over `phase` and return the WorkflowFailed it SAVED.

    Rehydrated from the JSON taken at save time, not read off the aggregate,
    which keeps mutating after the save.
    """
    _, saved = await _run(workspace, phase, skill_materializer=skill_materializer)
    (failed,) = [
        WorkflowFailedEvent.model_validate_json(raw)
        for event_type, raw in saved
        if event_type is WorkflowFailedEvent
    ]
    return failed


async def _run(
    workspace: AsyncMock,
    phase: ExecutablePhase,
    *,
    skill_materializer: AsyncMock | None = None,
) -> tuple[WorkflowExecutionResult, list[tuple[type, str]]]:
    """Run the real processor; return its result and every event saved, as JSON."""
    workspace_cm = AsyncMock()
    workspace_cm.__aenter__ = AsyncMock(return_value=workspace)
    workspace_cm.__aexit__ = AsyncMock(return_value=False)
    workspace_service = MagicMock()
    workspace_service.create_workspace.return_value = workspace_cm

    processor = WorkflowExecutionProcessor(
        execution_repository=AsyncMock(),
        session_repository=AsyncMock(),
        workspace_service=workspace_service,
        artifact_repository=AsyncMock(),
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=AsyncMock(return_value="Do the task"),
        command_builder=MagicMock(return_value=["claude", "--print", "Do the task"]),
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
        skill_materializer=skill_materializer,
    )
    saved: list[tuple[type, str]] = []

    async def _snapshot(aggregate: object) -> None:
        for envelope in aggregate.get_uncommitted_events():  # type: ignore[attr-defined]
            saved.append((type(envelope.event), envelope.event.model_dump_json()))

    # Private reach, as the sibling tests do: there is no event store here.
    processor._journal._repository.save = AsyncMock(side_effect=_snapshot)

    with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as mock_secrets:
        mock_secrets.create = AsyncMock(return_value=MagicMock())
        result: WorkflowExecutionResult = await processor.run(
            workflow_id="wf-1",
            workflow_name="Fix the thing",
            phases=[phase],
            inputs={},
            execution_id="exec-80394dfd862a",
        )

    assert result.status == "failed"
    return result, saved


async def test_a_setup_phase_killed_mid_clone_is_not_recorded_as_a_clone() -> None:
    """The #1158 reproduction, read from the field it was reported from."""
    persisted = await _persisted_error(
        _workspace(
            setup=ExecutionResult(
                exit_code=SIGKILLED,
                success=False,
                duration_ms=1200.0,
                stderr=CLONE_PROGRESS,
            )
        ),
        _phase(),
    )

    assert "SIGKILL" in persisted, persisted
    assert str(SIGKILLED) in persisted, persisted
    # The progress may still be quoted - it is the last thing anyone saw - but
    # only after the status, and only once the message has said it is not an
    # error. Leading with it is the bug.
    assert persisted.index("SIGKILL") < persisted.index(CLONE_PROGRESS), persisted
    assert "not an error message" in persisted, persisted


async def test_a_setup_phase_that_timed_out_says_so_rather_than_quoting_progress() -> None:
    """A timeout reports no status at all, so output alone is all there was.

    The isolation providers return -1 here, meaning "never ran to completion".
    Reading -1 as a signal number would invent a SIGHUP death; reading its
    stderr as the reason invents a git failure. Both have happened.
    """
    persisted = await _persisted_error(
        _workspace(
            setup=ExecutionResult(
                exit_code=-1,
                success=False,
                duration_ms=600_000.0,
                stderr=CLONE_PROGRESS,
                timed_out=True,
            )
        ),
        _phase(),
    )

    assert "timed out" in persisted, persisted
    assert "SIGHUP" not in persisted, persisted
    assert persisted.index("timed out") < persisted.index(CLONE_PROGRESS), persisted
    # PC-126: a timeout is a loaded host, not a broken setup. The record names
    # the step and says a resume clears it - the sentence `failure_account`'s
    # upstream kind adds, so this proves the kind reached the failure path.
    assert "Provision step secret_injection" in persisted, persisted
    assert "transient; the phase is resumable" in persisted, persisted


async def test_a_setup_phase_that_failed_is_not_called_transient() -> None:
    """Only a timeout is a loaded host; an exit status is the setup's own answer."""
    persisted = await _persisted_error(
        _workspace(
            setup=ExecutionResult(exit_code=1, success=False, duration_ms=900.0, stderr="no")
        ),
        _phase(),
    )

    assert "transient" not in persisted, persisted


async def test_a_setup_phase_that_really_failed_still_leads_with_its_reason() -> None:
    """The demotion is conditional: a process that CHOSE its status did fail.

    Without this, "say the output is not an error" becomes true of every
    failure and the message stops carrying the diagnosis at all.
    """
    persisted = await _persisted_error(
        _workspace(
            setup=ExecutionResult(
                exit_code=1,
                success=False,
                duration_ms=900.0,
                stderr="fatal: could not read Username for 'https://github.com'",
            )
        ),
        _phase(),
    )

    assert "exited 1" in persisted, persisted
    assert "could not read Username" in persisted, persisted
    assert "not an error message" not in persisted, persisted


async def test_a_skill_install_killed_mid_download_is_not_recorded_as_the_skill_failing() -> None:
    """The same discard, two methods over, on the same persisted field.

    ``skills add`` fetches over the network and prints progress while it does,
    so an install killed at the phase budget recorded that progress as its
    reason. The exit status was in the message but unlabelled - "(exit 137)" -
    which is a number an operator has to already know to read.
    """
    download_progress = "Fetching skill 'code-review' from https://github.com/example ..."
    workspace = _workspace(
        setup=ExecutionResult(exit_code=0, success=True, duration_ms=10.0),
        command=ExecutionResult(
            exit_code=SIGKILLED,
            success=False,
            duration_ms=5000.0,
            stderr=download_progress,
        ),
    )
    materializer = AsyncMock()
    materializer.fetch_for_workspace = AsyncMock(return_value=[])
    skill = ResolvedSkill(
        skill_name="code-review",
        source_url="https://github.com/example/code-review",
        version="1.0.0",
        resolved_sha="sha-1",
        tree_storage_prefix="prefix/sha-1",
    )

    persisted = await _persisted_error(
        workspace, _phase(skills=(skill,)), skill_materializer=materializer
    )

    assert "SIGKILL" in persisted, persisted
    assert persisted.index("SIGKILL") < persisted.index(download_progress), persisted
    assert "not an error message" in persisted, persisted


async def test_a_skill_install_that_never_ran_invents_no_exit_status() -> None:
    """Nothing ran, so there is no status to report and none is fabricated.

    This path used to pass ``exit_code=-1`` with its explanation in the
    ``stderr`` argument, so a refusal decided before any container work read
    as a command that had run and failed.
    """
    workspace = _workspace(setup=ExecutionResult(exit_code=0, success=True, duration_ms=10.0))
    materializer = AsyncMock()
    materializer.fetch_for_workspace = AsyncMock(return_value=[])
    clashing = (
        ResolvedSkill(
            skill_name="code-review",
            source_url="https://github.com/example/code-review",
            version="1.0.0",
            resolved_sha="sha-1",
            tree_storage_prefix="prefix/sha-1",
        ),
        ResolvedSkill(
            skill_name="code-review",
            source_url="https://github.com/example/code-review",
            version="2.0.0",
            resolved_sha="sha-2",
            tree_storage_prefix="prefix/sha-2",
        ),
    )

    persisted = await _persisted_error(
        workspace, _phase(skills=clashing), skill_materializer=materializer
    )

    assert "was not attempted" in persisted, persisted
    assert "conflicting versions of skill" in persisted, persisted
    assert "exit" not in persisted, persisted


async def test_a_skill_install_that_timed_out_twice_is_recorded_as_transient() -> None:
    """PC-126 (exec-f4fa08b81ecc): one timeout is retried, the second is resumable."""
    timed_out = ExecutionResult(
        exit_code=-1,
        success=False,
        duration_ms=240_000.0,
        stderr="Fetching skill 'code-review' ...",
        timed_out=True,
    )
    workspace = _workspace(setup=ExecutionResult(exit_code=0, success=True, duration_ms=10.0))
    workspace.execute = AsyncMock(return_value=timed_out)
    materializer = AsyncMock()
    materializer.fetch_for_workspace = AsyncMock(return_value=[])
    skill = ResolvedSkill(
        skill_name="code-review",
        source_url="https://github.com/example/code-review",
        version="1.0.0",
        resolved_sha="sha-1",
        tree_storage_prefix="prefix/sha-1",
    )

    with patch(
        "syn_domain.contexts.orchestration.slices.execute_workflow.handlers.skill_install.asyncio.sleep",
        AsyncMock(),
    ):
        persisted = await _persisted_error(
            workspace, _phase(skills=(skill,)), skill_materializer=materializer
        )

    installs = [c for c in workspace.execute.await_args_list if c.args[0][:2] == ["skills", "add"]]
    assert len(installs) == 2
    assert "Provision step skill_install" in persisted, persisted
    assert "'code-review'" in persisted, persisted
    assert "transient; the phase is resumable" in persisted, persisted


async def test_a_setup_timeout_stores_a_transient_platform_failure() -> None:
    """PC-126 (exec-72b96da7a046): the stored event carries the structured kind."""
    failed = await _stored_failure(
        _workspace(
            setup=ExecutionResult(exit_code=-1, success=False, duration_ms=1.0, timed_out=True)
        ),
        _phase(),
    )

    assert failed.failure_classification is FailureClassification.PLATFORM
    assert failed.upstream_failure_kind is UpstreamFailureKind.UNAVAILABLE
    assert "Provision step secret_injection" in failed.error_message


async def test_a_setup_refusal_stores_no_transient_kind() -> None:
    failed = await _stored_failure(
        _workspace(setup=ExecutionResult(exit_code=1, success=False, duration_ms=1.0, stderr="no")),
        _phase(),
    )

    assert failed.upstream_failure_kind is None


async def test_a_skill_install_timed_out_twice_stores_a_transient_platform_failure() -> None:
    timed_out = ExecutionResult(exit_code=-1, success=False, duration_ms=1.0, timed_out=True)
    workspace = _workspace(setup=ExecutionResult(exit_code=0, success=True, duration_ms=10.0))
    workspace.execute = AsyncMock(return_value=timed_out)
    materializer = AsyncMock()
    materializer.fetch_for_workspace = AsyncMock(return_value=[])
    skill = ResolvedSkill(
        skill_name="code-review",
        source_url="https://github.com/example/code-review",
        version="1.0.0",
        resolved_sha="sha-1",
        tree_storage_prefix="prefix/sha-1",
    )

    with patch(
        "syn_domain.contexts.orchestration.slices.execute_workflow.handlers.skill_install.asyncio.sleep",
        AsyncMock(),
    ):
        failed = await _stored_failure(
            workspace, _phase(skills=(skill,)), skill_materializer=materializer
        )

    assert failed.failure_classification is FailureClassification.PLATFORM
    assert failed.upstream_failure_kind is UpstreamFailureKind.UNAVAILABLE
    assert "Provision step skill_install" in failed.error_message
