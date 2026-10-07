"""A resumed run's `WorkflowExecutionStarted` lands in both execution read models (#1696).

On 2026-10-07 two resumes' starts were passed by `workflow_executions` and
`workflow_execution_details` without being applied: checkpoints above them, no
row. Both start handlers treat a resume start exactly like a fresh one, and
the first class here shows it: the events the real resume path writes,
dispatched through the real coordinator, produce every row, at every depth of
resume, the same on replay.

What did lose them is the coordinator. A handler that failed was logged and
stepped over, and the projection's next event checkpointed past it. That is
fixed in event-sourcing-platform (`ProjectionHandlerFailedError`), and the
second class pins it from this side: it is a strict xfail until the
`lib/event-sourcing-platform` gitlink carries the fix, and the bump that
brings it in must delete the marker, because the test then passes.

The event store here is keyed by aggregate id alone and numbers events in
the order they are saved, which is all a projection sees of the real one
(ESP #344).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest
from event_sourcing import MemoryCheckpointStore, SubscriptionCoordinator

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
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
    from collections.abc import Awaitable, Callable

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

    async def test_redelivered_history_changes_nothing(self) -> None:
        """A reconnect re-sends what is at or below the checkpoint: it must be a no-op."""
        history = await _history()
        store = InMemoryProjectionStore()
        coordinator = _coordinator(store)
        for envelope in history:
            await coordinator.dispatch_event(envelope)
        before = {name: await store.get_all(name) for name in READ_MODELS}

        for envelope in history:
            await coordinator.dispatch_event(envelope)

        assert {name: await store.get_all(name) for name in READ_MODELS} == before


def _fails_once_for[**P](
    key: str, save: Callable[P, Awaitable[None]]
) -> Callable[P, Awaitable[None]]:
    """``save``, except the first write of ``key`` raises, the way a store blip does."""
    failed = False

    async def blipping(*args: P.args, **kwargs: P.kwargs) -> None:
        nonlocal failed
        if not failed and key in args:
            failed = True
            raise ConnectionError("projection store unavailable")
        await save(*args, **kwargs)

    return blipping


class TestAFailedStartIsNotSteppedOver:
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "#1696: needs ProjectionHandlerFailedError from event-sourcing-platform; "
            "delete this marker in the gitlink bump that brings it in"
        ),
    )
    async def test_a_resume_start_that_hit_a_store_blip_is_applied_on_redelivery(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        history = await _history()
        started = _started_at(history)
        store = InMemoryProjectionStore()
        monkeypatch.setattr(store, "save", _fails_once_for(RESUME, store.save))
        coordinator = _coordinator(store)

        for envelope in history:
            try:
                await coordinator.dispatch_event(envelope)
            except Exception:  # ProjectionHandlerFailedError, once the gitlink carries it
                # What start() does after a failed attempt: deliver it again
                # from the held checkpoint.
                await coordinator.dispatch_event(envelope)

        list_row = await store.get(WorkflowExecutionListProjection.PROJECTION_NAME, RESUME)
        assert list_row is not None
        assert _instant(list_row["started_at"]) == started[RESUME]
