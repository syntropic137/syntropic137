"""The one load-edit-save path behind every tag edit (#967).

Adding or removing tags is the same four steps on a workflow and on an
execution: load the aggregate, let it decide, save what it emitted, publish.
Both slices go through here so the two cannot drift apart -- in particular
on what an edit that changes nothing does, which is succeed and write nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from event_sourcing import DomainEvent, EventEnvelope

    from syn_domain.repository import Repository


class TagEditableAggregate(Protocol):
    """What the edit path needs from an aggregate beyond its own command."""

    def get_uncommitted_events(self) -> list[EventEnvelope[DomainEvent]]: ...

    def mark_events_as_committed(self) -> None: ...


class EventPublisher(Protocol):
    """Protocol for publishing domain events."""

    async def publish(self, events: list[EventEnvelope[DomainEvent]]) -> None:
        """Publish domain events for integration."""
        ...


@dataclass(frozen=True)
class TagEditResult[T]:
    """The outcome of a tag edit.

    ``tags`` is the aggregate's tags after the edit, set on success only.
    ``error`` names the broken rule on failure. A missing aggregate is not a
    result at all: the edit returns ``None``.
    """

    success: bool
    error: str = ""
    tags: T | None = None


async def edit_tags[A: TagEditableAggregate, T](
    repository: Repository[A],
    aggregate_id: str,
    edit: Callable[[A], None],
    tags_of: Callable[[A], T],
    event_publisher: EventPublisher | None = None,
) -> TagEditResult[T] | None:
    """Load, apply ``edit``, save and publish. ``None`` if the id is unknown."""
    aggregate = await repository.get_by_id(aggregate_id)
    if aggregate is None:
        return None

    try:
        edit(aggregate)
    except ValueError as e:
        # InvalidTagsError is a ValueError: the per-record limit is enforced
        # here, against the tags the aggregate already carries.
        return TagEditResult(success=False, error=str(e))

    # Get events before save (save may mark as committed)
    events = aggregate.get_uncommitted_events()
    if events:
        await repository.save(aggregate)
        if event_publisher is not None:
            await event_publisher.publish(events)
        aggregate.mark_events_as_committed()

    return TagEditResult(success=True, tags=tags_of(aggregate))
