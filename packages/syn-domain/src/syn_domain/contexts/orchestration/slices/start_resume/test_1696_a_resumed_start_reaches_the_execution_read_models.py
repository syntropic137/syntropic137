"""A resumed run's `WorkflowExecutionStarted` lands in both execution read models (#1696).

On 2026-10-07 two resumes' starts were missing from `workflow_executions` and
`workflow_execution_details` while both read models had checkpointed above
them. That loss was not in these handlers or in the coordinator: the deployed
event store let a later append commit ahead of an earlier one, so its cursor
moved past events it had never delivered (#1708, fixed by ESP #337 / event
store v0.16+). No handler change recovers an event that is never delivered,
and nothing here reproduces that race.

What this module pins is the domain side. The first class shows both start
handlers treat a resume start exactly like a fresh one: the events the real
resume path writes, dispatched through the real coordinator, produce every
row, at every depth of resume, the same on replay, and checkpointed
redelivery applies nothing. The second shows a start naming no execution is a
dispatch FAILURE rather than a silent SUCCESS checkpointed past.

The coordinator's own guarantee, that a failed event holds its projection
and is retried rather than stepped over, came in with ESP v0.17.0 (#1737) and
is covered there by `test_coordinator_never_steps_over_a_failed_event.py`.
These tests do not re-prove it.

The event store here is a list in memory: keyed by aggregate id alone, it
numbers events in the order they are saved and every save is visible at
once. It cannot commit out of order, persist a checkpoint, or survive a
restart, so it says nothing about any of those (ESP #344).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest
from event_sourcing import MemoryCheckpointStore, ProjectionResult, SubscriptionCoordinator

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration._shared.unapplied_start import UnappliableStartError
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ResumeExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)
from syn_domain.contexts.orchestration.slices.start_resume import StartResumeHandler
from syn_domain.contexts.orchestration.slices.start_resume.test_start_resume import (
    PARENT,
    RESUME,
    _ArtifactQuery,
    _Executions,
    _failed_in_plan,
    _processor,
    _Provisioned,
)
from syn_domain.testing.fake_agent_handler import A_DELIVERABLE, FakeAgentExecutionHandler

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope

pytestmark = pytest.mark.unit

#: A resume of RESUME, so its inherited phases are owned two streams up.
RESUME_OF_RESUME = "exec-resume-grandchild"
READ_MODELS = (
    WorkflowExecutionListProjection.PROJECTION_NAME,
    WorkflowExecutionDetailProjection.PROJECTION_NAME,
)


class _NumberedExecutions(_Executions):
    """Execution streams, plus every event in the order it was stored."""

    def __init__(self) -> None:
        super().__init__()
        self.log: list[EventEnvelope[DomainEvent]] = []

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        for envelope in aggregate.get_uncommitted_events():
            stored = envelope.metadata.model_copy(
                update={
                    "global_nonce": len(self.log) + 1,
                    "event_type": envelope.event.event_type,
                }
            )
            self.log.append(envelope.model_copy(update={"metadata": stored}))
        await super().save(aggregate)


async def _resume(executions: _NumberedExecutions, parent_id: str, child_id: str) -> None:
    parent = executions.streams[parent_id]
    parent.resume_execution(
        ResumeExecutionCommand(
            execution_id=parent_id, resume_execution_id=child_id, acknowledge_external_effects=True
        )
    )
    await executions.save(parent)


async def _start(
    executions: _NumberedExecutions, parent_id: str, agent: FakeAgentExecutionHandler
) -> str:
    handler = StartResumeHandler(
        _processor(executions, agent, _Provisioned(), _ArtifactQuery()), executions
    )
    result = await handler.handle(parent_id)
    assert result is not None
    return result.status


async def _history() -> list[EventEnvelope[DomainEvent]]:
    """A fresh run that fails, its resume that fails, and that resume's resume."""
    executions = _NumberedExecutions()
    await _failed_in_plan(executions)
    await _resume(executions, PARENT, RESUME)
    failing = FakeAgentExecutionHandler.scripted(
        FakeAgentExecutionHandler.success(produces=A_DELIVERABLE),
        FakeAgentExecutionHandler.failed(exit_code=1),
    )
    assert await _start(executions, PARENT, failing) == "failed"
    await _resume(executions, RESUME, RESUME_OF_RESUME)
    succeeding = FakeAgentExecutionHandler.success(produces=A_DELIVERABLE)
    assert await _start(executions, RESUME, succeeding) == "completed"
    return executions.log


def _coordinator(store: InMemoryProjectionStore) -> SubscriptionCoordinator:
    return SubscriptionCoordinator(
        event_store=None,  # type: ignore[arg-type]  # fed through dispatch_event only
        checkpoint_store=MemoryCheckpointStore(),
        projections=[
            WorkflowExecutionListProjection(store),
            WorkflowExecutionDetailProjection(store),
        ],
    )


def _instant(value: object) -> datetime | None:
    """A stored start time, whichever form the read model keeps it in."""
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value if isinstance(value, datetime) else None


def _started_at(history: list[EventEnvelope[DomainEvent]]) -> dict[str, datetime | None]:
    """Each run's start time, as its own `WorkflowExecutionStarted` recorded it."""
    return {
        envelope.metadata.aggregate_id: _instant(envelope.event.model_dump()["started_at"])
        for envelope in history
        if envelope.metadata.event_type == "WorkflowExecutionStarted"
    }


async def _rows(store: InMemoryProjectionStore) -> list[tuple[str, str, datetime | None]]:
    """(read model, execution, started_at) for every row."""
    rows: list[tuple[str, str, datetime | None]] = []
    for name in READ_MODELS:
        for row in await store.get_all(name):
            execution_id = row.get("execution_id") or row.get("workflow_execution_id")
            rows.append((name, str(execution_id), _instant(row.get("started_at"))))
    return sorted(rows)


class TestEveryStartLands:
    async def test_a_fresh_start_a_resume_and_a_resume_of_a_resume(self) -> None:
        history = await _history()
        started = _started_at(history)
        assert set(started) == {PARENT, RESUME, RESUME_OF_RESUME}

        store = InMemoryProjectionStore()
        coordinator = _coordinator(store)
        for envelope in history:
            await coordinator.dispatch_event(envelope)

        expected = sorted(
            (name, execution_id, started_at)
            for name in READ_MODELS
            for execution_id, started_at in started.items()
        )
        assert await _rows(store) == expected

    async def test_replaying_from_zero_gives_the_same_rows(self) -> None:
        history = await _history()
        first, again = InMemoryProjectionStore(), InMemoryProjectionStore()
        live = _coordinator(first)
        for envelope in history:
            await live.dispatch_event(envelope)
        replay = _coordinator(again)
        for envelope in history:
            await replay.dispatch_event(envelope)

        for name in READ_MODELS:
            assert await again.get_all(name) == await first.get_all(name)

    async def test_redelivered_history_writes_nothing(self) -> None:
        """A reconnect re-sends what is at or below the checkpoint: it must apply none of it.

        The rows are cleared before the redelivery, so any event the
        coordinator hands a handler again writes a row back. Comparing the
        rows to themselves could not tell a skipped event from one reapplied
        to the same result.
        """
        history = await _history()
        store = InMemoryProjectionStore()
        coordinator = _coordinator(store)
        for envelope in history:
            await coordinator.dispatch_event(envelope)
        for name in READ_MODELS:
            assert await store.get_all(name)
            await store.delete_all(name)

        for envelope in history:
            await coordinator.dispatch_event(envelope)

        assert {name: await store.get_all(name) for name in READ_MODELS} == {
            name: [] for name in READ_MODELS
        }


class TestAStartThatCannotBeAppliedIsNotPassed:
    """A start naming no execution fails the dispatch instead of checkpointing past it.

    Returning without a write is read as SUCCESS and checkpointed, which is a
    silent skip. The resume path never writes such a start; the read models
    still must not pass one quietly if one is ever stored.
    """

    @pytest.mark.parametrize("read_model", READ_MODELS)
    async def test_the_checkpoint_stays_below_it_and_the_error_is_logged(
        self, read_model: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        history = await _history()
        first = history[0]
        assert first.metadata.event_type == "WorkflowExecutionStarted"
        malformed = first.model_copy(
            update={
                "event": first.event.model_copy(update={"execution_id": ""}),
                "metadata": first.metadata.model_copy(update={"global_nonce": 2}),
            }
        )
        store = InMemoryProjectionStore()
        projection = {
            WorkflowExecutionListProjection.PROJECTION_NAME: WorkflowExecutionListProjection,
            WorkflowExecutionDetailProjection.PROJECTION_NAME: WorkflowExecutionDetailProjection,
        }[read_model](store)
        checkpoints = MemoryCheckpointStore()

        assert await projection.handle_event(first, checkpoints) == ProjectionResult.SUCCESS
        rows = await store.get_all(read_model)
        result = await projection.handle_event(malformed, checkpoints)

        assert result == ProjectionResult.FAILURE
        checkpoint = await checkpoints.get_checkpoint(read_model)
        assert checkpoint is not None
        assert checkpoint.global_position == 1
        assert await store.get_all(read_model) == rows
        raised = [r.exc_info[1] for r in caplog.records if r.exc_info]
        assert any(isinstance(e, UnappliableStartError) for e in raised)
