"""The signal name must survive the hop into the stored record (#1295).

#1295 was reported from stored executions, not from stack traces: the operator
read ``error_message`` and found ``exit code -11 (no stderr output)``. So the
test that matters drives the real processor over a phase whose secret-injection
step is killed by a signal, and reads the field they actually read. A name
produced in the handler and dropped at the record would pass a test of the
handler alone.
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

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

FAILING_PHASE_NAME = "Prepare the workspace"

#: What #1295 reported, with no stderr - so the code IS the whole diagnosis.
SEGFAULTED_SETUP = ExecutionResult(exit_code=-11, success=False, duration_ms=430.0)

#: Distinctive enough that finding it in the record cannot be a coincidence.
SETUP_STDERR = "fatal: could not read Username for 'https://github.com'"

#: THE CASE THE FIRST FIXTURE CANNOT REACH, and the reason this constant
#: exists. The failure path read `stderr or <exit code>`, so it only ever
#: consulted the exit code when stderr was EMPTY - which is what
#: ``SEGFAULTED_SETUP`` is. A setup script that fails has usually printed
#: something, so the realistic shape of #1295 is this one: killed by a signal
#: AND chatty, the combination in which the -11 was dropped. A test using only
#: the fixture above passes on a handler that still drops it.
SEGFAULTED_SETUP_WITH_STDERR = ExecutionResult(
    exit_code=-11,
    success=False,
    duration_ms=430.0,
    stderr=SETUP_STDERR,
)


def _the_failing_phase() -> ExecutablePhase:
    return ExecutablePhase(
        phase_id="phase-1",
        name=FAILING_PHASE_NAME,
        order=1,
        description="",
        agent_config=AgentConfiguration(),
        prompt_template="Do the task",
        output_artifact_types=("text",),
    )


def _workspace_service_whose_setup_returns(setup_result: ExecutionResult) -> MagicMock:
    workspace = AsyncMock()
    workspace.proxy_url = "http://envoy:10000"
    workspace.workspace_id = "ws-1295"
    workspace.run_setup_phase = AsyncMock(return_value=setup_result)

    workspace_cm = AsyncMock()
    workspace_cm.__aenter__ = AsyncMock(return_value=workspace)
    workspace_cm.__aexit__ = AsyncMock(return_value=False)

    workspace_service = MagicMock()
    workspace_service.create_workspace.return_value = workspace_cm
    return workspace_service


async def test_the_handler_names_the_signal() -> None:
    async def fake_prompt_builder(*_args: object, **_kwargs: object) -> str:
        return "Do the task"

    handler = WorkspaceProvisionHandler(
        workspace_service=_workspace_service_whose_setup_returns(SEGFAULTED_SETUP),
        prompt_builder=fake_prompt_builder,
        command_builder=lambda _phase, prompt: ["claude", "--print", prompt],
    )

    with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as mock_secrets:
        mock_secrets.create = AsyncMock(return_value=MagicMock())
        with pytest.raises(RuntimeError) as excinfo:
            await handler.handle(
                todo=TodoItem(
                    execution_id="exec-76a6d3b22b23",
                    action=TodoAction.PROVISION_WORKSPACE,
                    phase_id="phase-1",
                ),
                phase=_the_failing_phase(),
                workflow_id="wf-1",
                session_id="sess-1",
                repos=[],
            )

    assert "killed by SIGSEGV (exit -11)" in str(excinfo.value)


@pytest.mark.parametrize(
    ("setup_result", "expected"),
    [
        pytest.param(SEGFAULTED_SETUP, ("-11", "SIGSEGV"), id="silent"),
        pytest.param(
            SEGFAULTED_SETUP_WITH_STDERR,
            ("-11", "SIGSEGV", SETUP_STDERR),
            id="stderr-present",
        ),
    ],
)
async def test_the_execution_record_an_operator_reads_names_the_signal(
    setup_result: ExecutionResult,
    expected: tuple[str, ...],
) -> None:
    """The field #1295 was actually reported from.

    Both cases, because the two of them take DIFFERENT BRANCHES and only one
    of them was ever exercised. The silent one reaches the "no stderr output"
    fallback; the chatty one is the case the fallback never sees, and it is
    the case in which the exit code used to be thrown away entirely. They must
    end up in the same record carrying the same three facts - how it ended,
    what that means, and what it said on the way out - because an operator
    reading one of these has no way to know which branch produced it.
    """
    from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
    from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
        WorkflowExecutionProcessor,
    )
    from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
        ExecutionTodoProjection,
    )

    processor = WorkflowExecutionProcessor(
        execution_repository=AsyncMock(),
        session_repository=AsyncMock(),
        workspace_service=_workspace_service_whose_setup_returns(setup_result),
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
            execution_id="exec-76a6d3b22b23",
        )

    assert result.status == "failed"
    assert result.error_message is not None
    for fact in expected:
        assert fact in result.error_message, result.error_message
