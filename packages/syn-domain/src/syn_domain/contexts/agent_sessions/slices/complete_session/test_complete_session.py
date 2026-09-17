"""Tests for CompleteSession handler.

The handler's body was a comment describing what it would do followed by
``pass`` (#1034), and the API's ``complete_session()`` returned Ok on top
of it. So these tests assert against a REREAD session, never against the
aggregate the test itself completed.
"""

from __future__ import annotations

import pytest
from event_sourcing import DomainEvent, EventEnvelope  # noqa: TC002

from syn_domain.contexts.agent_sessions._shared.value_objects import SessionStatus
from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
    AgentSessionAggregate,
)
from syn_domain.contexts.agent_sessions.domain.commands.CompleteSessionCommand import (
    CompleteSessionCommand,
)
from syn_domain.contexts.agent_sessions.domain.commands.StartSessionCommand import (
    StartSessionCommand,
)

from .CompleteSessionHandler import CompleteSessionHandler


class FakeSessionRepository:
    """An event-sourced repository double: a stream per aggregate.

    ``get_by_id`` rehydrates a FRESH aggregate from the saved stream, so a
    handler that completes an aggregate without saving it leaves the reread
    session still running - the shape of the no-op this replaced.
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
            workflow_id="wf-complete",
            execution_id="exec-complete",
            phase_id="phase-1",
            agent_provider="claude",
        )
    )
    await repo.save(session)


@pytest.mark.unit
async def test_handler_persists_the_completion() -> None:
    """The session must read back as completed, not merely stop erroring."""
    repo = FakeSessionRepository()
    await _running_session(repo, "sess-complete-1")

    await CompleteSessionHandler(repository=repo).handle(
        CompleteSessionCommand(aggregate_id="sess-complete-1", success=True)
    )

    persisted = await repo.get_by_id("sess-complete-1")
    assert persisted is not None
    assert persisted.status == SessionStatus.COMPLETED


@pytest.mark.unit
async def test_failure_is_persisted_with_its_reason() -> None:
    """A failed completion must carry the reason downstream, not just a status."""
    repo = FakeSessionRepository()
    await _running_session(repo, "sess-complete-2")

    await CompleteSessionHandler(repository=repo).handle(
        CompleteSessionCommand(
            aggregate_id="sess-complete-2",
            success=False,
            error_message="agent exited 137",
        )
    )

    events = repo.recorded_events("sess-complete-2")
    assert [type(e).__name__ for e in events] == ["SessionStartedEvent", "SessionCompletedEvent"]
    completed = events[-1]
    assert completed.status == SessionStatus.FAILED
    assert completed.error_message == "agent exited 137"


@pytest.mark.unit
async def test_unknown_session_is_an_error_not_a_silent_no_op() -> None:
    """The no-op the handler replaced swallowed every command it was given."""
    repo = FakeSessionRepository()

    with pytest.raises(ValueError, match="not found"):
        await CompleteSessionHandler(repository=repo).handle(
            CompleteSessionCommand(aggregate_id="sess-missing", success=True)
        )

    assert repo.streams == {}


@pytest.mark.unit
async def test_aggregate_still_owns_the_rules() -> None:
    """A session that already reached a terminal status refuses to complete twice."""
    repo = FakeSessionRepository()
    await _running_session(repo, "sess-complete-3")
    handler = CompleteSessionHandler(repository=repo)
    await handler.handle(CompleteSessionCommand(aggregate_id="sess-complete-3", success=True))

    with pytest.raises(ValueError, match="session is completed"):
        await handler.handle(CompleteSessionCommand(aggregate_id="sess-complete-3", success=False))

    events = repo.recorded_events("sess-complete-3")
    assert [type(e).__name__ for e in events].count("SessionCompletedEvent") == 1
