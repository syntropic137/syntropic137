"""Make what has been appended visible to the read models (#1215).

Every writer in this system ends the same way: ``repository.save(aggregate)``
appends, and then the read models have to catch up before anyone can see the
result. Which mechanism does the catching up depends on the process, and this
function is the seam that hides that choice from the writer.

In production the ``CoordinatorSubscriptionService`` pulls from the durable
event store on its own schedule (ADR-055), so there is nothing for a writer to
push and this is a no-op -- ``NoOpEventPublisher`` has no stored events. In
test and offline runs there is no subscription, so the events the
``InMemoryEventPublisher`` collected are dispatched here instead.

It lives beside the publisher and the projection manager it joins, rather than
in the API's composition root, because the API is not its only caller:
``scripts/backfill/backfill_artifact_created_at.py`` is a migration and must not
have to import a web application to state that its writes should be readable.
"""

from __future__ import annotations


async def sync_published_events_to_projections() -> None:
    """Dispatch anything the in-memory publisher collected to the projections.

    Safe and meaningless to call in production; the caller does not have to know
    which it is. Call it after saving an aggregate, exactly as the API routes do
    -- a writer that skips it is correct in production and silently invisible
    everywhere else, which is the worst of the two failure modes because it only
    shows up where nobody is looking.
    """
    from syn_adapters.projections.manager import get_projection_manager
    from syn_adapters.storage import get_event_publisher
    from syn_adapters.storage.in_memory import InMemoryEventPublisher

    publisher = get_event_publisher()
    if not isinstance(publisher, InMemoryEventPublisher):
        return

    manager = get_projection_manager()
    for envelope in publisher.get_published_events():
        await manager.process_event_envelope(envelope)

    # Clear processed events so a second call does not re-dispatch them.
    publisher.clear()
