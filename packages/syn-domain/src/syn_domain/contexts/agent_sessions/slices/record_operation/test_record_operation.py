"""Tests for RecordOperation handler.

The handler's body was a comment describing what it would do followed by
``pass`` (#1034), so every test here has to assert against what was
PERSISTED, never against the command that went in.
"""

from __future__ import annotations

import pytest
from event_sourcing import DomainEvent, EventEnvelope  # noqa: TC002

from syn_domain.contexts.agent_sessions._shared.value_objects import OperationType
from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
    AgentSessionAggregate,
)
from syn_domain.contexts.agent_sessions.domain.commands.RecordOperationCommand import (
    RecordOperationCommand,
)
from syn_domain.contexts.agent_sessions.domain.commands.StartSessionCommand import (
    StartSessionCommand,
)

from .RecordOperationHandler import RecordOperationHandler


class FakeSessionRepository:
    """An event-sourced repository double: a stream per aggregate.

    ``get_by_id`` rehydrates a FRESH aggregate from the saved stream rather
    than handing back the object it was given. That is what makes these
    tests able to fail: a handler that loads and mutates but never saves
    leaves the stream untouched, so the next read shows no operation at all
    - which is exactly the shape of the no-op this replaced.
    """

    def __init__(self) -> None:
        self.streams: dict[str, list[EventEnvelope[DomainEvent]]] = {}

    async def get_by_id(self, aggregate_id: str) -> AgentSessionAggregate | None:
        stream = self.streams.get(aggregate_id)
        if not stream:
            return None
        session = AgentSessionAggregate()
        session.rehydrate(stream)
        return session

    async def save(self, aggregate: AgentSessionAggregate) -> None:
        self.streams.setdefault(str(aggregate.id), []).extend(aggregate.get_uncommitted_events())
        aggregate.mark_events_as_committed()

    async def save_new(self, aggregate: AgentSessionAggregate) -> None:
        await self.save(aggregate)

    async def exists(self, aggregate_id: str) -> bool:
        return aggregate_id in self.streams

    def recorded_events(self, aggregate_id: str) -> list[DomainEvent]:
        """The domain events on the stream, as downstream readers see them."""
        return [envelope.event for envelope in self.streams.get(aggregate_id, [])]


async def _running_session(repo: FakeSessionRepository, session_id: str) -> None:
    session = AgentSessionAggregate()
    session.start_session(
        StartSessionCommand(
            aggregate_id=session_id,
            workflow_id="wf-record-op",
            execution_id="exec-record-op",
            phase_id="phase-1",
            agent_provider="claude",
        )
    )
    await repo.save(session)


def _tool_completed(session_id: str) -> RecordOperationCommand:
    return RecordOperationCommand(
        aggregate_id=session_id,
        operation_type=OperationType.TOOL_EXECUTION_COMPLETED,
        tool_name="Bash",
        tool_use_id="toolu_slice_1034",
        tool_output="slice-1034-output",
        duration_seconds=1.5,
        input_tokens=4000,
        output_tokens=321,
        total_tokens=4321,
    )


@pytest.mark.unit
async def test_handler_persists_the_operation() -> None:
    """The operation must be on the aggregate the repository holds afterwards."""
    repo = FakeSessionRepository()
    await _running_session(repo, "sess-record-1")

    await RecordOperationHandler(repository=repo).handle(_tool_completed("sess-record-1"))

    persisted = await repo.get_by_id("sess-record-1")
    assert persisted is not None
    assert persisted.operation_count == 1
    operation = persisted.operations[0]
    assert operation.operation_type == OperationType.TOOL_EXECUTION_COMPLETED
    assert operation.tool_name == "Bash"
    assert operation.tool_use_id == "toolu_slice_1034"
    assert operation.tool_output == "slice-1034-output"
    assert persisted.tokens.total_tokens == 4321


@pytest.mark.unit
async def test_handler_emits_the_event_for_downstream_readers() -> None:
    """Persisting is not enough: the OperationRecorded event is what every
    projection and the realtime stream actually consume."""
    repo = FakeSessionRepository()
    await _running_session(repo, "sess-record-2")

    await RecordOperationHandler(repository=repo).handle(_tool_completed("sess-record-2"))

    events = repo.recorded_events("sess-record-2")
    assert [type(e).__name__ for e in events] == ["SessionStartedEvent", "OperationRecordedEvent"]
    recorded = events[-1]
    assert recorded.tool_use_id == "toolu_slice_1034"
    assert recorded.tool_output == "slice-1034-output"
    assert recorded.total_tokens == 4321


@pytest.mark.unit
async def test_unknown_session_is_an_error_not_a_silent_no_op() -> None:
    """The no-op the handler replaced swallowed every command it was given."""
    repo = FakeSessionRepository()

    with pytest.raises(ValueError, match="not found"):
        await RecordOperationHandler(repository=repo).handle(_tool_completed("sess-missing"))

    assert repo.streams == {}


@pytest.mark.unit
async def test_aggregate_still_owns_the_rules() -> None:
    """A completed session refuses more operations, and the handler does not
    paper over the refusal by saving anyway."""
    from syn_domain.contexts.agent_sessions.domain.commands.CompleteSessionCommand import (
        CompleteSessionCommand,
    )

    repo = FakeSessionRepository()
    await _running_session(repo, "sess-record-3")
    completed = await repo.get_by_id("sess-record-3")
    assert completed is not None
    completed.complete_session(CompleteSessionCommand(aggregate_id="sess-record-3", success=True))
    await repo.save(completed)

    with pytest.raises(ValueError, match="session is completed"):
        await RecordOperationHandler(repository=repo).handle(_tool_completed("sess-record-3"))

    reread = await repo.get_by_id("sess-record-3")
    assert reread is not None
    assert reread.operation_count == 0
