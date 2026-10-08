"""#1381: a platform shutdown saves the run's work and records it INTERRUPTED, then tears down.

Each test cancels a real `_run_started` task the way
`BackgroundWorkflowDispatcher.shutdown` does - `task.cancel()`, then awaiting
it - while a phase is in flight. What is observed is the consumer's view: the
events the journal handed to the store, and the order in which the save, the
append and the teardown happened. V1a-V1d of the #1310 plan.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    StartExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowInterruptedEvent import (
    WorkflowInterruptedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow import shutdown_interruption
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    QuarantinedWork,
    SavedWork,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    StreamResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionResult,
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
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
        _DispatchContext,
    )

EXECUTION = "exec-1381"
WORKFLOW = "wf-1381"
PHASE = "implement"
QUARANTINE_REF = "refs/syn/lost/exec-1381/implement"
#: Tokens the phase had burned when shutdown landed. Only the interruption
#: path reads them, so seeing them on the event is seeing that path run.
SPENT = (1381, 137)

_SAVED = SavedWork(
    quarantined=(
        QuarantinedWork(
            repo="syntropic137/syntropic137",
            branch="feat/x",
            commit_count=2,
            files=("a.py",),
            pushed_ref=QUARANTINE_REF,
        ),
    )
)


class _Harness:
    """A real processor with one phase in flight, and a log of what happened in what order."""

    def __init__(self, *, budget: float = 5.0) -> None:
        self.order: list[str] = []
        self.in_flight = asyncio.Event()
        #: Every event the store was handed, as the store received it.
        self.stored: list[object] = []
        self.repository = AsyncMock()
        self.repository.save_new.side_effect = self._save_new
        self.repository.save.side_effect = self._save
        self.processor = WorkflowExecutionProcessor(
            execution_repository=self.repository,
            session_repository=AsyncMock(),
            workspace_service=MagicMock(),
            artifact_repository=AsyncMock(),
            artifact_content_storage=None,
            artifact_query=None,
            conversation_storage=None,
            observability_writer=None,
            controller=None,
            prompt_builder=AsyncMock(return_value="prompt"),
            command_builder=MagicMock(return_value=["claude"]),
            todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
            interrupt_budget_seconds=budget,
        )
        runtime = self.processor._runtimes.of(EXECUTION)  # pyright: ignore[reportPrivateUsage]
        tokens = TokenAccumulator()
        tokens.record(*SPENT)
        runtime.record_agent_run(
            PHASE,
            execution_id=EXECUTION,
            result=AgentExecutionResult(
                StreamResult(line_count=1, interrupt_requested=False, interrupt_reason=None),
                tokens,
                SubagentTracker(),
                command=None,
            ),
        )
        self.runtime = runtime
        self.save_work = self._save_work
        runtime.save_unpushed_work = self._dispatch_save  # type: ignore[method-assign]
        real_abandon = runtime.abandon_all

        async def abandon_all(context: str) -> None:
            self.order.append(f"abandon:{context}")
            await real_abandon(context)

        runtime.abandon_all = abandon_all  # type: ignore[method-assign]
        self.processor._drain_todo_list = self._drain  # type: ignore[method-assign]

    async def _drain(self, *, dispatch_ctx: _DispatchContext, **_: object) -> None:
        dispatch_ctx.current_phase_id = PHASE
        dispatch_ctx.kept_artifact_ids.append("artifact-kept-1381")
        self.in_flight.set()
        await asyncio.Event().wait()  # the agent, minutes long

    async def _dispatch_save(self, phase_id: str | None, *, execution_id: str) -> SavedWork:
        return await self.save_work(phase_id, execution_id=execution_id)

    async def _save_work(self, phase_id: str | None, *, execution_id: str) -> SavedWork:
        assert (phase_id, execution_id) == (PHASE, EXECUTION)
        self.order.append("save")
        return _SAVED

    async def _save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.stored.extend(e.event for e in aggregate.get_uncommitted_events())
        aggregate.mark_events_as_committed()

    async def _save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.order.append(f"append:{aggregate.status.value}")
        self.stored.extend(e.event for e in aggregate.get_uncommitted_events())
        aggregate.mark_events_as_committed()

    def start(self) -> asyncio.Task[object]:
        aggregate = WorkflowExecutionAggregate()
        aggregate.start_execution(
            StartExecutionCommand(
                execution_id=EXECUTION,
                workflow_id=WORKFLOW,
                workflow_name="Shutdown",
                total_phases=1,
                inputs={},
            )
        )
        self.aggregate = aggregate
        return asyncio.create_task(
            self.processor._run_started(  # pyright: ignore[reportPrivateUsage]
                aggregate, WORKFLOW, [], {}, None, None
            )
        )

    def interruptions(self) -> list[WorkflowInterruptedEvent]:
        return [e for e in self.stored if isinstance(e, WorkflowInterruptedEvent)]


async def _shut_down(task: asyncio.Task[object]) -> None:
    """What `BackgroundWorkflowDispatcher.shutdown` does to each execution task."""
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.unit
@pytest.mark.anyio
async def test_v1a_a_single_cancel_saves_records_interrupted_then_tears_down() -> None:
    h = _Harness()
    task = h.start()
    await h.in_flight.wait()

    await _shut_down(task)

    assert task.cancelled(), "the cancel must still propagate to the dispatcher"
    assert h.aggregate.status is ExecutionStatus.INTERRUPTED
    assert h.order == ["save", "append:interrupted", "abandon:shutdown"]
    (event,) = h.interruptions()
    assert event.phase_id == PHASE
    assert (event.partial_input_tokens, event.partial_output_tokens) == SPENT
    assert "artifact-kept-1381" in event.partial_artifact_ids
    assert QUARANTINE_REF in (event.reason or "")


@pytest.mark.unit
@pytest.mark.anyio
async def test_v1b_a_second_cancel_during_the_sequence_does_not_skip_it() -> None:
    h = _Harness()
    release = asyncio.Event()
    saving = asyncio.Event()

    async def slow_save(phase_id: str | None, *, execution_id: str) -> SavedWork:
        saving.set()
        await release.wait()
        return await h._save_work(phase_id, execution_id=execution_id)

    h.save_work = slow_save
    task = h.start()
    await h.in_flight.wait()

    task.cancel()
    async with asyncio.timeout(5):  # without the handler nothing ever saves
        await saving.wait()
    task.cancel()  # the second cancel, mid-save
    await asyncio.sleep(0)
    assert h.order == [], "teardown must not start while the save is running"
    release.set()
    await asyncio.gather(task, return_exceptions=True)

    assert task.cancelled()
    assert h.order == ["save", "append:interrupted", "abandon:shutdown"]
    assert len(h.interruptions()) == 1


@pytest.mark.unit
@pytest.mark.anyio
async def test_v1c_a_refused_append_is_logged_not_retried_and_teardown_still_runs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    h = _Harness()
    attempts: list[str] = []

    async def refuse(aggregate: WorkflowExecutionAggregate) -> None:
        attempts.append(aggregate.status.value)
        msg = "event store unavailable"
        raise ConnectionError(msg)

    task = h.start()
    await h.in_flight.wait()
    h.repository.save.side_effect = refuse

    with caplog.at_level(logging.ERROR):
        await _shut_down(task)

    assert task.cancelled()
    assert attempts == ["interrupted"], "one attempt, no retry inside the budget"
    assert h.order == ["save", "abandon:shutdown"]
    assert any(
        EXECUTION in r.getMessage() and "event store refused" in r.getMessage()
        for r in caplog.records
        if r.levelno == logging.ERROR
    )


@pytest.mark.unit
@pytest.mark.anyio
async def test_v1d_a_push_hanging_past_the_budget_is_cut_off_and_awaited_before_teardown(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutdown_interruption, "_SETTLE_AFTER_CANCEL_SECONDS", 1.0)
    h = _Harness(budget=0.2)
    push_cancelled = asyncio.Event()

    async def hanging_push(phase_id: str | None, *, execution_id: str) -> SavedWork:
        h.order.append("save")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            # The salvage honours a cancel only after a short bound of its own.
            await asyncio.sleep(0.1)
            h.order.append("push-settled")
            push_cancelled.set()
            raise
        return _SAVED  # pragma: no cover

    h.save_work = hanging_push
    task = h.start()
    await h.in_flight.wait()

    with caplog.at_level(logging.ERROR):
        async with asyncio.timeout(5):
            await _shut_down(task)

    assert task.cancelled()
    assert push_cancelled.is_set()
    # Teardown only after the cut-off push settled: never under a live push.
    assert h.order == ["save", "push-settled", "abandon:shutdown"]
    assert h.interruptions() == [], "left RUNNING for startup reconciliation"
    assert h.aggregate.status is ExecutionStatus.RUNNING
    assert any(
        EXECUTION in r.getMessage() and "within" in r.getMessage()
        for r in caplog.records
        if r.levelno == logging.ERROR
    )


@pytest.mark.unit
@pytest.mark.anyio
async def test_shutdown_between_phases_records_no_invented_phase_or_usage() -> None:
    h = _Harness()

    async def between_phases(*, dispatch_ctx: _DispatchContext, **_: object) -> None:
        assert dispatch_ctx.current_phase_id is None
        h.in_flight.set()
        await asyncio.Event().wait()

    h.processor._drain_todo_list = between_phases  # type: ignore[method-assign]
    h.runtime.save_unpushed_work = AsyncMock(return_value=SavedWork())  # type: ignore[method-assign]
    task = h.start()
    await h.in_flight.wait()
    await _shut_down(task)

    (event,) = h.interruptions()
    assert event.phase_id == ""
    assert (event.partial_input_tokens, event.partial_output_tokens) == (0, 0)
    assert event.partial_artifact_ids == []
    assert h.aggregate.status is ExecutionStatus.INTERRUPTED
    h.runtime.save_unpushed_work.assert_awaited_once_with(None, execution_id=EXECUTION)


@pytest.mark.unit
@pytest.mark.anyio
async def test_shutdown_before_agent_result_has_no_fabricated_usage() -> None:
    h = _Harness()
    h.runtime._auth_tokens.clear()  # pyright: ignore[reportPrivateUsage]
    task = h.start()
    await h.in_flight.wait()
    await _shut_down(task)

    (event,) = h.interruptions()
    assert (event.partial_input_tokens, event.partial_output_tokens) == (0, 0)
    assert h.order == ["save", "append:interrupted", "abandon:shutdown"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_shutdown_keeps_every_dropped_artifact_once() -> None:
    h = _Harness()
    h.processor._workspaces_for = MagicMock(  # type: ignore[method-assign]
        return_value=MagicMock(
            keep_dropped_workflows=AsyncMock(
                return_value=["artifact-kept-1381", "workflow-a", "workflow-b", "workflow-a"]
            )
        )
    )
    task = h.start()
    await h.in_flight.wait()
    await _shut_down(task)

    (event,) = h.interruptions()
    expected = {"artifact-kept-1381", "workflow-a", "workflow-b"}
    assert set(event.partial_artifact_ids) == expected
    for artifact in expected:
        assert event.partial_artifact_ids.count(artifact) == 1


@pytest.mark.unit
@pytest.mark.anyio
async def test_shutdown_does_not_relabel_a_durably_cancelled_execution() -> None:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        CancelExecutionCommand,
    )

    h = _Harness()
    task = h.start()
    await h.in_flight.wait()
    h.aggregate.cancel_execution(
        CancelExecutionCommand(execution_id=EXECUTION, phase_id=PHASE, reason="user stop")
    )
    await h.processor._journal.append(h.aggregate)  # pyright: ignore[reportPrivateUsage]
    await _shut_down(task)

    assert h.aggregate.status is ExecutionStatus.CANCELLED
    assert h.interruptions() == []
    assert h.order == ["append:cancelled", "abandon:shutdown"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_a_failure_after_budget_expiry_is_reported_before_teardown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    h = _Harness(budget=0.01)

    async def failing_on_cancel(phase_id: str | None, *, execution_id: str) -> SavedWork:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise ConnectionError("salvage failed while settling") from None

    h.save_work = failing_on_cancel
    task = h.start()
    await h.in_flight.wait()
    with caplog.at_level(logging.ERROR):
        await _shut_down(task)

    assert task.cancelled()
    assert h.aggregate.status is ExecutionStatus.RUNNING
    assert h.order == ["abandon:shutdown"]
    assert any(
        record.name == shutdown_interruption.__name__
        and record.exc_info is not None
        and isinstance(record.exc_info[1], ConnectionError)
        and EXECUTION in record.getMessage()
        for record in caplog.records
    ), "settling failures must be consumed and reported, not lost as task warnings"
