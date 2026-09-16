"""An event-sourced session repository double.

``SessionLifecycleManager`` used to hold one aggregate for the life of a
phase and save it; its tests could therefore get away with a save-only stub.
It now delegates to the ``agent_sessions`` slice handlers, which load by id
(#1034), so a double that cannot be read from turns the whole write path into
a no-op again - the exact failure this issue is about.

``get_by_id`` rehydrates a FRESH aggregate from the saved stream rather than
handing back the object it was given. That is what makes tests using this
double able to fail: a write that never reaches ``save`` is invisible to the
next read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
    AgentSessionAggregate,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope


class FakeSessionRepository:
    """In-memory ``Repository[AgentSessionAggregate]`` - one stream per session."""

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
