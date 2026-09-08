"""The setup failure an operator reads must name WHICH setup and WHICH phase (#1236).

Two different things are called "setup": the workflow phase commonly named
"Prepare the workspace", and the ADR-024 secret-injection step that runs inside
EVERY phase. Issue #1236 recorded an execution where the second one failed and
the record said "Setup phase failed", so the operator went to the first one and
found it green.

These tests exercise the message an operator actually sees - the RuntimeError
text that becomes the execution's ``error_message`` - not the value object that
formats it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    WorkspaceProvisionHandler,
)

#: The phase that failed in #1236. Distinct from any default a stub might carry,
#: and distinct from the "Prepare the workspace" phase that completed.
FAILING_PHASE_NAME = "Make the change"


def _workspace_service_whose_setup_returns(setup_result: ExecutionResult) -> MagicMock:
    """A workspace service whose ADR-024 setup step returns ``setup_result``."""
    workspace = AsyncMock()
    workspace.proxy_url = "http://envoy:10000"
    workspace.workspace_id = "ws-1236"
    workspace.run_setup_phase = AsyncMock(return_value=setup_result)

    workspace_cm = AsyncMock()
    workspace_cm.__aenter__ = AsyncMock(return_value=workspace)
    workspace_cm.__aexit__ = AsyncMock(return_value=False)

    workspace_service = MagicMock()
    workspace_service.create_workspace.return_value = workspace_cm
    return workspace_service


def _the_failing_phase() -> ExecutablePhase:
    return ExecutablePhase(
        phase_id="phase-2",
        name=FAILING_PHASE_NAME,
        order=2,
        description="",
        agent_config=AgentConfiguration(),
        prompt_template="Do the task",
        output_artifact_types=("text",),
    )


async def _provision_error_message(setup_result: ExecutionResult) -> str:
    """Provision a phase whose setup step fails; return the operator-facing text."""

    async def fake_prompt_builder(*_args: object, **_kwargs: object) -> str:
        return "Do the task"

    def fake_command_builder(_phase: object, prompt: str) -> list[str]:
        return ["claude", "--print", prompt]

    handler = WorkspaceProvisionHandler(
        workspace_service=_workspace_service_whose_setup_returns(setup_result),
        prompt_builder=fake_prompt_builder,
        command_builder=fake_command_builder,
    )
    todo = TodoItem(
        execution_id="exec-80394dfd862a",
        action=TodoAction.PROVISION_WORKSPACE,
        phase_id="phase-2",
    )
    phase = _the_failing_phase()

    with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as mock_secrets:
        mock_secrets.create = AsyncMock(return_value=MagicMock())
        with pytest.raises(RuntimeError) as excinfo:
            await handler.handle(
                todo=todo,
                phase=phase,
                workflow_id="wf-1",
                session_id="sess-1",
                repos=[],
            )
    return str(excinfo.value)


@pytest.mark.unit
@pytest.mark.anyio
async def test_setup_failure_names_the_secret_injection_step_and_the_phase() -> None:
    message = await _provision_error_message(
        ExecutionResult(
            exit_code=1,
            success=False,
            duration_ms=1200.0,
            stderr="fatal: could not read Username for 'https://github.com'",
        )
    )

    # Names WHICH setup...
    assert "Secret-injection setup failed" in message
    # ...and WHICH phase, so nobody goes looking at "Prepare the workspace".
    assert f"phase '{FAILING_PHASE_NAME}'" in message
    # The bare wording that sent the operator to the wrong phase is gone.
    assert "Setup phase failed" not in message
    # The diagnosis itself survives the rewording.
    assert "could not read Username" in message


@pytest.mark.unit
@pytest.mark.anyio
async def test_signal_death_records_the_signal_name_and_what_the_step_wrote() -> None:
    """#1236's SIGSEGV left `exit code -11 (no stderr output)` and nothing else."""
    message = await _provision_error_message(
        ExecutionResult(
            exit_code=-11,
            success=False,
            duration_ms=10_000.0,
            stdout="Cloning into 'syntropic137'...\nSubmodule path 'lib/agentic-primitives'\n",
            stderr="",
        )
    )

    assert "SIGSEGV" in message
    # Whatever it DID write before dying, rather than "(no stderr output)".
    assert "Submodule path 'lib/agentic-primitives'" in message
    assert f"phase '{FAILING_PHASE_NAME}'" in message


@pytest.mark.unit
@pytest.mark.anyio
async def test_setup_failure_with_no_output_at_all_still_names_setup_and_phase() -> None:
    message = await _provision_error_message(
        ExecutionResult(exit_code=-11, success=False, duration_ms=10_000.0)
    )

    assert "Secret-injection setup failed" in message
    assert f"phase '{FAILING_PHASE_NAME}'" in message
    assert "SIGSEGV" in message
    assert "no output captured" in message


@pytest.mark.unit
@pytest.mark.anyio
async def test_the_execution_record_an_operator_reads_names_the_setup_and_the_phase() -> None:
    """The message has to survive the hop from the handler into the RECORD.

    #1236 was reported from the stored execution, not from a stack trace: the
    operator read ``error_message`` and went to the wrong phase. So run the
    real processor over a phase whose in-phase setup dies, and read the field
    they actually read.
    """
    from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
    from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
        WorkflowExecutionProcessor,
    )
    from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
        ExecutionTodoProjection,
    )

    workspace_service = _workspace_service_whose_setup_returns(
        ExecutionResult(exit_code=-11, success=False, duration_ms=10_000.0, stderr="")
    )
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
    )
    processor._journal._repository.save = AsyncMock()

    with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as mock_secrets:
        mock_secrets.create = AsyncMock(return_value=MagicMock())
        result = await processor.run(
            workflow_id="wf-1",
            workflow_name="Fix the thing",
            phases=[_the_failing_phase()],
            inputs={},
            execution_id="exec-80394dfd862a",
        )

    assert result.status == "failed"
    assert result.error_message is not None
    assert "Secret-injection setup failed" in result.error_message
    assert f"phase '{FAILING_PHASE_NAME}'" in result.error_message
    assert "SIGSEGV" in result.error_message
    assert "Setup phase failed" not in result.error_message
