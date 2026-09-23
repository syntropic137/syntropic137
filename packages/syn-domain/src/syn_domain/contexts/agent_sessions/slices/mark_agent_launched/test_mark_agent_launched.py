"""Tests for MarkAgentLaunched handler.

The slice had no test file and a handler whose body was ``pass`` (#1034).
The launch fact is the discriminator between "the agent never ran" and
"the agent ran and later failed" (#1047, #1065), so a handler that drops
it silently turns one of those into the other.
"""

from __future__ import annotations

import pytest
from event_sourcing import DomainEvent, EventEnvelope  # noqa: TC002

from syn_domain.contexts.agent_sessions._shared.value_objects import AgentLaunch
from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
    AgentSessionAggregate,
)
from syn_domain.contexts.agent_sessions.domain.commands.MarkAgentLaunchedCommand import (
    MarkAgentLaunchedCommand,
)
from syn_domain.contexts.agent_sessions.domain.commands.StartSessionCommand import (
    StartSessionCommand,
)

from .MarkAgentLaunchedHandler import MarkAgentLaunchedHandler


class FakeSessionRepository:
    """An event-sourced repository double: a stream per aggregate.

    ``get_by_id`` rehydrates a FRESH aggregate from the saved stream, so a
    handler that marks an aggregate without saving it leaves the reread
    session NOT_LAUNCHED - the shape of the no-op this replaced.
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
            workflow_id="wf-launch",
            execution_id="exec-launch",
            phase_id="phase-1",
            agent_provider="claude",
        )
    )
    await repo.save(session)


@pytest.mark.unit
async def test_handler_persists_the_launch_fact() -> None:
    """The reread session must say LAUNCHED - a fresh one says NOT_LAUNCHED."""
    repo = FakeSessionRepository()
    await _running_session(repo, "sess-launch-1")

    before = await repo.get_by_id("sess-launch-1")
    assert before is not None
    assert before.agent_launch is AgentLaunch.NOT_LAUNCHED

    await MarkAgentLaunchedHandler(repository=repo).handle(
        MarkAgentLaunchedCommand(aggregate_id="sess-launch-1")
    )

    after = await repo.get_by_id("sess-launch-1")
    assert after is not None
    assert after.agent_launch is AgentLaunch.LAUNCHED
    assert [type(e).__name__ for e in repo.recorded_events("sess-launch-1")] == [
        "SessionStartedEvent",
        "AgentLaunchedEvent",
    ]


@pytest.mark.unit
async def test_redispatch_appends_no_second_event() -> None:
    """The aggregate makes this idempotent; a defensive re-dispatch after a
    crash must not put a second AgentLaunched on the stream."""
    repo = FakeSessionRepository()
    await _running_session(repo, "sess-launch-2")
    handler = MarkAgentLaunchedHandler(repository=repo)
    command = MarkAgentLaunchedCommand(aggregate_id="sess-launch-2")

    await handler.handle(command)
    await handler.handle(command)

    events = [type(e).__name__ for e in repo.recorded_events("sess-launch-2")]
    assert events.count("AgentLaunchedEvent") == 1


@pytest.mark.unit
async def test_unknown_session_is_an_error_not_a_silent_no_op() -> None:
    """The no-op the handler replaced swallowed every command it was given."""
    repo = FakeSessionRepository()

    with pytest.raises(ValueError, match="not found"):
        await MarkAgentLaunchedHandler(repository=repo).handle(
            MarkAgentLaunchedCommand(aggregate_id="sess-missing")
        )

    assert repo.streams == {}
