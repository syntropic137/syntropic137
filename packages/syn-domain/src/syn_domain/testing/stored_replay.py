"""Replay what an in-memory event store holds, as the real store hands it back.

``MemoryEventStoreClient`` keeps the event OBJECTS it was given and leaves
``metadata.event_type`` unset, so a projection fed straight from it neither
dispatches (the type is how ``AutoDispatchProjection`` routes) nor sees the
payload a serializer actually writes. This round-trips each event through
JSON and its own class and stamps the type, which is what a read off the
real store looks like to a projection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from event_sourcing import (
        AutoDispatchProjection,
        DomainEvent,
        EventEnvelope,
        ProjectionCheckpointStore,
    )
    from event_sourcing.client.memory import MemoryEventStoreClient


async def stored_envelopes(client: MemoryEventStoreClient) -> list[EventEnvelope[DomainEvent]]:
    """Every event in global order, as written to and read back from JSON."""
    envelopes, _end, _next = await client.read_all(max_count=1_000_000)
    return [
        envelope.model_copy(
            update={
                "event": type(envelope.event).model_validate_json(envelope.event.model_dump_json()),
                "metadata": envelope.metadata.model_copy(
                    update={"event_type": envelope.event.event_type}
                ),
            }
        )
        for envelope in envelopes
    ]


async def replay(
    client: MemoryEventStoreClient,
    checkpoints: ProjectionCheckpointStore,
    *projections: AutoDispatchProjection,
) -> None:
    """Dispatch the stored stream into each projection via ``handle_event``."""
    for envelope in await stored_envelopes(client):
        for projection in projections:
            await projection.handle_event(envelope, checkpoints)
