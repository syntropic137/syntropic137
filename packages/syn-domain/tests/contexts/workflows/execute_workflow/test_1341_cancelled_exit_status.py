"""#1341: a CANCELLED run's unobserved exit status is unknown, not a clean 0.

THE LAST HIDING PLACE OF THE #1319 DEFECT. `_detect_exit_code` stopped
returning 0 for "nobody observed a status" everywhere except one branch: when
`interrupt_requested` was set, it still returned 0. The justification on the
books was that the cancel path is routed on `interrupt_requested` and never
reads the number - so the 0 was harmless.

It was not harmless, for two reasons this module pins:

1. `record_phase_conversation` stores `success=result.command.exit_code == 0`
   BEFORE the processor's `interrupt_requested` routing runs. The sentinel
   therefore filed every cancelled phase's transcript as a SUCCESS.
2. Nothing stops that command reaching the aggregate later; "no consumer reads
   it today" is a property of today's callers, not of the value.

A cancelled run is expressed by the PATH it takes - `ExecutionCancelledEvent`,
which carries no exit status at all - so the number never needed to carry that
meaning. `None` is the honest answer here exactly as it is everywhere else.

These drive the REAL `AgentExecutionHandler` over a stream that is interrupted
mid-run, which is how a real cancellation ends: `EventStreamProcessor` calls
`workspace.interrupt()` and breaks the read loop immediately, without waiting
for the process to report a status. So "cancelled, and no status observed" is
the ORDINARY cancellation, not an edge case.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_adapters.control.commands import ControlSignal, ControlSignalType
from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.workspace_backends.memory import MemoryEventStreamAdapter
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.testing.fake_session_repository import FakeSessionRepository

# The same recorder the #1319 tests read their events through: same real
# handler, same serialized wire form, so the two sets of claims are directly
# comparable rather than two harnesses that happen to agree.
from .test_1319_real_handler_exit_status import _Run
from .test_processor_smoke import (
    FakeArtifactRepository,
    FakeExecutionRepository,
    _noop_command_builder,
    _noop_prompt_builder,
    _one_phase_workflow,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_adapters.conversations import SessionContext
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )

pytestmark = pytest.mark.unit

#: `CancelSignalPoller` checks only on line counts that are multiples of its
#: poll interval (10), so the stream must get past one for the cancel to fire
#: at all. Enough lines to cross it and keep going.
LINES_BEFORE_CANCEL = 25


class _StreamInterruptedMidRun(MemoryEventStreamAdapter):
    """A stream cancelled part-way through, reporting no exit status.

    The exit code is assigned only after the final yield, so a consumer that
    breaks out early never reaches it and `last_stream_exit_code` stays None.
    That is not a contrivance for the test - it is precisely what the
    production loop does on cancel (`EventStreamProcessor._process_line`
    interrupts and breaks), and it is why an unobserved status is the normal
    outcome of a cancellation rather than a rare one.
    """

    async def stream(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
        wrapper_name: str | None = None,
    ) -> AsyncIterator[str]:
        for _ in range(LINES_BEFORE_CANCEL):
            yield '{"type":"assistant","message":{"content":[]}}'
        # Only reached if nobody interrupted: a status the cancelled run
        # must never be credited with.
        self._last_exit_code = 0


class _ControllerThatCancels:
    """Answers every poll with CANCEL, as a user hitting cancel would."""

    async def check_signal(self, execution_id: str) -> ControlSignal:
        return ControlSignal(
            signal_type=ControlSignalType.CANCEL,
            execution_id=execution_id,
            reason="cancelled by user",
        )


async def _run_a_phase_cancelled_mid_stream() -> _Run:
    """Run a one-phase workflow that is cancelled before any status is observed."""
    workspace_service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)
    workspace_service._event_stream = _StreamInterruptedMidRun()  # pyright: ignore[reportPrivateUsage]

    processor = WorkflowExecutionProcessor(
        execution_repository=FakeExecutionRepository(),
        session_repository=FakeSessionRepository(),
        workspace_service=workspace_service,
        artifact_repository=FakeArtifactRepository(),
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        # The real handler, built per call by the processor, so
        # `_detect_exit_code` and the guard it feeds are under test.
        controller=_ControllerThatCancels(),  # pyright: ignore[reportArgumentType]
        prompt_builder=_noop_prompt_builder,
        command_builder=_noop_command_builder,
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
        agent_handler=None,
    )

    repository = processor._journal._repository  # pyright: ignore[reportPrivateUsage]
    recorded: list[object] = []
    original_save = repository.save

    async def capturing_save(aggregate: object) -> None:
        recorded.extend(e.event for e in aggregate.get_uncommitted_events())  # pyright: ignore[reportAttributeAccessIssue]
        await original_save(aggregate)

    repository.save = capturing_save  # pyright: ignore[reportAttributeAccessIssue]

    result = await processor.run(
        workflow_id="wf-1341-cancel",
        workflow_name="Cancelled before any exit status was observed",
        phases=_one_phase_workflow(),
        inputs={},
        execution_id="exec-1341-cancel",
    )
    return _Run(result.status, recorded)


class TestACancelledRunIsCancelledNotFailed:
    """The routing must keep working once the sentinel is gone.

    Removing the 0 without moving the `interrupt_requested` check ahead of the
    "no status" guard would turn every cancellation into a FAILED execution -
    trading one wrong answer for a worse one. This is the test that refuses
    that trade, and it is why the fix is two edits rather than one.
    """

    @pytest.mark.anyio
    async def test_the_execution_is_recorded_as_cancelled(self) -> None:
        run = await _run_a_phase_cancelled_mid_stream()

        assert run.status == "cancelled", (
            f"a run stopped by a cancel signal must be cancelled, not {run.status!r}"
        )

    @pytest.mark.anyio
    async def test_the_cancellation_is_what_reaches_the_stream(self) -> None:
        run = await _run_a_phase_cancelled_mid_stream()

        assert len(run.of_type("ExecutionCancelledEvent")) == 1, (
            "the cancel path records ExecutionCancelledEvent; that event, not an "
            "exit status, is what says the run was cancelled"
        )


class TestNoCancelledRunIsCreditedWithACleanExit:
    """The defect itself: 0 meant 'exited cleanly' in the one case nobody looked."""

    @pytest.mark.anyio
    async def test_no_event_claims_the_agent_completed_with_zero(self) -> None:
        """`AgentExecutionCompleted` carries exit_code into the read model.

        Emitting it here would put "this phase exited cleanly" on the durable
        stream for a run that was killed before anything could observe it.
        """
        run = await _run_a_phase_cancelled_mid_stream()

        completed = run.of_type("AgentExecutionCompletedEvent")
        assert completed == [], (
            f"a cancelled run may claim no completion, least of all a clean one; got {completed}"
        )

    @pytest.mark.anyio
    async def test_the_phase_transcript_is_not_filed_as_a_success(self) -> None:
        """The consumer that read the sentinel, one hop before the cancel routing.

        `record_phase_conversation` computes `success = exit_code == 0` and runs
        BEFORE the processor checks `interrupt_requested`, so it saw the
        synthetic 0 and stored every cancelled phase as a success. This is the
        hop the object-level tests could not see.
        """
        stored: list[bool] = []

        class _CapturingConversationStorage:
            async def store_session(
                self, session_id: str, lines: list[str], context: SessionContext
            ) -> None:
                stored.append(bool(context.success))

        workspace_service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)
        workspace_service._event_stream = _StreamInterruptedMidRun()  # pyright: ignore[reportPrivateUsage]
        processor = WorkflowExecutionProcessor(
            execution_repository=FakeExecutionRepository(),
            session_repository=FakeSessionRepository(),
            workspace_service=workspace_service,
            artifact_repository=FakeArtifactRepository(),
            artifact_content_storage=None,
            artifact_query=None,
            conversation_storage=_CapturingConversationStorage(),  # pyright: ignore[reportArgumentType]
            observability_writer=None,
            controller=_ControllerThatCancels(),  # pyright: ignore[reportArgumentType]
            prompt_builder=_noop_prompt_builder,
            command_builder=_noop_command_builder,
            todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
            agent_handler=None,
        )
        await processor.run(
            workflow_id="wf-1341-conv",
            workflow_name="Cancelled, transcript must not read as success",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1341-conv",
        )

        assert stored, "the phase transcript was never stored; this asserts nothing yet"
        assert not any(stored), (
            "a cancelled phase whose exit status nobody observed was filed as a "
            f"successful conversation; success flags stored: {stored}"
        )
