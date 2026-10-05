"""A trigger joins the eval that was the default when it was ACCEPTED (#967).

The dispatcher accepts a trigger, then queues its task for an execution-budget
slot for as long as the execution ahead of it runs. A workflow's default eval can
change in that window. The run must still join the eval, at the SHAs, that
were in force when the trigger was accepted: the dispatch projection has
already recorded the trigger as dispatched, and a run whose eval depended on
queue timing would be a different experiment for a reason nobody chose.

The dispatcher and its budget are real; only the handler is a double, and
it records the command it was handed. Determinism comes from ``asyncio.Event``
and the real budget, never from sleeps.
"""

from __future__ import annotations

import asyncio
import os

import pytest

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_api._wiring_admission import BackgroundWorkflowDispatcher
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration import EvalId, ExecuteWorkflowCommand, LaunchEval
from syn_domain.contexts.orchestration._shared.eval_choice import EvalChoice, EvalSelection
from syn_domain.contexts.orchestration._shared.repository_baseline import RepositoryBaseline

pytestmark = pytest.mark.unit

_PATIENCE = 5.0
_SHA_A = "a1" * 20
_SHA_B = "b2" * 20


class _WorkflowDefault:
    """The workflow's default eval and the SHA it froze, as admission reads it NOW."""

    def __init__(self) -> None:
        self.eval_id = "eval-a"
        self.sha = _SHA_A

    async def launch_eval_for(self, _workflow_id: str, _choice: EvalChoice) -> LaunchEval:
        return LaunchEval(
            EvalId(self.eval_id),
            EvalSelection.WORKFLOW_DEFAULT,
            (
                RepositoryBaseline(
                    repository=RepositoryRef.from_slug("acme/widgets"),
                    requested_ref="main",
                    commit_sha=self.sha,
                ),
            ),
        )


class _RecordingHandler:
    """Holds the first run inside the handler until the test lets it go."""

    def __init__(self) -> None:
        self.first_reached = asyncio.Event()
        self.release_first = asyncio.Event()
        self.second_handled = asyncio.Event()
        self.commands: dict[str, ExecuteWorkflowCommand] = {}

    async def validate_stored_declarations(self, _workflow_id: str) -> None:
        return None

    async def handle(self, command: ExecuteWorkflowCommand, *, admitted: object = None) -> None:
        execution_id = command.execution_id or ""
        self.commands[execution_id] = command
        if execution_id == "exec-first":
            self.first_reached.set()
            await self.release_first.wait()
        else:
            self.second_handled.set()


async def test_a_trigger_queued_behind_another_keeps_the_eval_it_was_accepted_into() -> None:
    default = _WorkflowDefault()
    handler = _RecordingHandler()
    dispatcher = BackgroundWorkflowDispatcher(
        handler,  # type: ignore[arg-type]  # the double records the command
        max_concurrent=1,
        launch_eval_for_workflow=default.launch_eval_for,
    )

    await dispatcher.run_workflow("wf-1", {}, "exec-first")
    async with asyncio.timeout(_PATIENCE):
        await handler.first_reached.wait()
    await dispatcher.run_workflow("wf-1", {}, "exec-second")

    # Accepted and queued; now the workflow's default moves to another eval.
    default.eval_id, default.sha = "eval-b", _SHA_B
    handler.release_first.set()
    async with asyncio.timeout(_PATIENCE):
        await handler.second_handled.wait()
    await dispatcher.shutdown()

    launch = handler.commands["exec-second"].launch_eval
    assert launch is not None
    assert str(launch.eval_id) == "eval-a"
    assert [pin.commit_sha for pin in launch.baseline] == [_SHA_A]
