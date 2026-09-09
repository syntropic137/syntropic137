"""A phase that says it could not do its job is not a completed phase (#1127).

The defect this pins is not a wrong value anywhere - it is a value that was
produced correctly at one hop and dropped at the next. The agent ends its
response with the `TASK_RESULT` block the platform prints into every prompt it
sends; the stream processor parsed it into an untyped dict, logged it, and
nothing downstream ever read it. So `verify` aborting - because its base ref
moved, because it had no input, because the head it was told to review was
gone - reached the aggregate as `completed`, indistinguishable from a review
that ran all its checks and found nothing.

WHY THESE RUN THE REAL PROCESSORS. The block is emitted by the agent as prose
inside a harness event, and the two harnesses put that prose in different
places: claude in a terminal `result` line, codex in an `item.completed` of
type `agent_message`. A test that constructed `StreamResult` by hand would
assert the guard's arithmetic while leaving either harness free to stop
carrying the report at all - which is precisely what codex did before this
change, having never parsed the contract it was being sent. Both are therefore
driven from raw JSONL, through `PhaseRuntime.record_agent_run`, to the
aggregate the processor would have told.

The assertions are about what the aggregate was told, never about the guard's
return value, for the same reason as `test_unpushed_work_guard.py`: the defect
is a phase REPORTED completed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.slices.execute_workflow.agent_self_report import (
    PhaseDeclaredItsOwnFailureError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    CodexStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        StreamResult,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_EXECUTION_ID = "exec-3afef2976abe"
_PHASE_ID = "verify"

#: Almost exactly what the verify phase said in exec-3afef2976abe, which was
#: recorded as a success. The prose is the point: it is unambiguous, a human
#: reading it knows no review happened, and it changed nothing.
_COULD_NOT_VERIFY = (
    "origin/main has moved since the investigate phase recorded it "
    "(a1b2c3d -> 9f8e7d6), and the head I was told to review is no longer "
    "reachable. I did not run any of the three checks.\n\n"
    'TASK_RESULT: {"success": false, "comments": "base ref moved; performed no verification"}'
)

_VERIFIED_AND_PASSED = (
    "I ran all three checks against the recorded head and the claim survived.\n\n"
    'TASK_RESULT: {"success": true, "comments": "claim holds"}'
)


class _Workspace:
    """Enough workspace for a stream processor; the guard never touches it."""

    last_stream_exit_code = 0

    async def interrupt(self) -> bool:
        return True


class _Collector:
    """Swallows the telemetry lane, which has no bearing on the verdict.

    Codex's processor writes a session summary unconditionally, so this is
    required to run it at all - not a stand-in for anything under test.
    """

    async def record_session_summary(self, **kwargs: object) -> None:
        return


async def _stream(*lines: str) -> AsyncIterator[str]:
    for line in lines:
        yield line


async def _claude_said(said: str) -> StreamResult:
    """What the REAL claude processor makes of an agent that said `said`."""
    processor = EventStreamProcessor(
        tokens=TokenAccumulator(),
        subagents=SubagentTracker(),
        observability=None,
        controller=None,
        execution_id=_EXECUTION_ID,
        phase_id=_PHASE_ID,
        session_id="sess-1",
        workspace_id="ws-1",
        agent_model="opus",
    )
    return await processor.process_stream(
        _stream(json.dumps({"type": "result", "subtype": "success", "result": said})),
        _Workspace(),
    )


async def _codex_said(said: str) -> StreamResult:
    """The same, for the harness the verify phase actually runs on."""
    processor = CodexStreamProcessor(
        tokens=TokenAccumulator(),
        collector=_Collector(),  # type: ignore[arg-type]
        controller=None,
        execution_id=_EXECUTION_ID,
        phase_id=_PHASE_ID,
        session_id="sess-1",
        agent_model="gpt-5.6-sol",
    )
    return await processor.process_stream(
        _stream(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "item-1", "type": "agent_message", "text": said},
                }
            )
        ),
        _Workspace(),
    )


class _PhaseAtCompletion:
    """A phase whose agent has exited, at the hop that reports it completed."""

    def __init__(self, stream_result: StreamResult) -> None:
        from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
        from syn_domain.contexts.orchestration import (
            AgentExecutionCompletedCommand,
            AgentExecutionResult,
        )
        from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
            ExecutionTodoProjection,
        )

        self.aggregate = MagicMock(workflow_id="sdlc-pr-review-v1")
        self.aggregate.get_uncommitted_events.return_value = []
        self.completed_phase_ids: list[str] = []
        self.processor = WorkflowExecutionProcessor(
            execution_repository=AsyncMock(),
            session_repository=AsyncMock(),
            workspace_service=MagicMock(),
            artifact_repository=AsyncMock(),
            artifact_content_storage=None,
            artifact_query=None,
            conversation_storage=None,
            observability_writer=None,
            controller=None,
            prompt_builder=AsyncMock(return_value="prompt"),
            command_builder=MagicMock(return_value=["codex"]),
            todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
        )
        self.processor._runtime.begin(
            _PHASE_ID,
            session_manager=AsyncMock(),
            started_at=datetime.now(UTC),
        )
        # The real hop the harness result travels through on its way to the
        # completion path. Bypassing it would leave `record_agent_run` free to
        # stop carrying the report and every assertion below still green.
        self.processor._runtime.record_agent_run(
            _PHASE_ID,
            AgentExecutionResult(
                stream_result=stream_result,
                tokens=TokenAccumulator(),
                subagents=SubagentTracker(),
                command=AgentExecutionCompletedCommand(
                    execution_id=_EXECUTION_ID,
                    phase_id=_PHASE_ID,
                    session_id="sess-1",
                    exit_code=0,
                ),
            ),
        )

    async def complete(self) -> None:
        await self.processor._handle_complete_phase(
            TodoItem(
                execution_id=_EXECUTION_ID,
                action=TodoAction.COMPLETE_PHASE,
                phase_id=_PHASE_ID,
                session_id="sess-1",
            ),
            self.aggregate,
            [],
            self.completed_phase_ids,
        )


@pytest.mark.parametrize("harness", ["claude", "codex"])
async def test_the_phase_that_could_not_verify_is_never_reported_completed(
    harness: str,
) -> None:
    """The consuming hop, for BOTH harnesses.

    The exit code is 0 and the artifact was written, so every other signal the
    platform has says this phase succeeded. The agent's own words are the only
    thing that says otherwise, and they must be enough.
    """
    said = await (_claude_said if harness == "claude" else _codex_said)(_COULD_NOT_VERIFY)
    phase = _PhaseAtCompletion(said)

    with pytest.raises(PhaseDeclaredItsOwnFailureError) as raised:
        await phase.complete()

    phase.aggregate.complete_phase.assert_not_called()
    assert phase.completed_phase_ids == []
    # The reason reaches the execution's error, not just a log line: an
    # operator reading `syn execution view` must be told what stopped it.
    assert "performed no verification" in str(raised.value)
    assert _PHASE_ID in str(raised.value)


@pytest.mark.parametrize("harness", ["claude", "codex"])
async def test_the_phase_that_verified_and_passed_still_completes(harness: str) -> None:
    """The other half of the invariant, and what makes the test above mean anything.

    A guard that refused every phase would pass the assertions above while
    making the platform useless. `success: true` must still be a pass.
    """
    said = await (_claude_said if harness == "claude" else _codex_said)(_VERIFIED_AND_PASSED)
    phase = _PhaseAtCompletion(said)

    await phase.complete()

    phase.aggregate.complete_phase.assert_called_once()
    assert phase.completed_phase_ids == [_PHASE_ID]


async def test_an_agent_that_declared_nothing_is_not_a_declared_failure() -> None:
    """Silence is silence, deliberately - not a failure and not a pass.

    Most phases in this platform are not verification gates, and an agent that
    forgets the block, or whose stream is truncated before it, has said nothing
    about its own outcome. Failing closed here would fail those phases on the
    strength of a missing sentence, which is a much wider blast radius than the
    signal justifies.
    """
    said = await _codex_said("I finished the work and pushed it.")
    assert said.agent_self_report is None

    phase = _PhaseAtCompletion(said)
    await phase.complete()

    phase.aggregate.complete_phase.assert_called_once()
