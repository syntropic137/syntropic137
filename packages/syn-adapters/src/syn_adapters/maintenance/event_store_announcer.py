"""Announce "admission is open" into the event stream (#1387).

The gate decides; this makes the decision reach consumers that were asleep.
An append rather than a broadcast because the requirement is durability: a
trigger paused by a deploy must still be dispatched if the API that cleared
maintenance mode dies immediately afterwards, and only something in the store
can outlive that process.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from event_sourcing import EventEnvelope, EventMetadata, ExpectedVersion

from syn_domain.contexts._shared.integration_events import AdmissionOpenEvent

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventStoreClient

    from syn_domain.contexts._shared.maintenance import MaintenanceMode

#: One stream for the whole system, not one per deploy. The announcements are
#: a small ordered log of "admission is open", and consumers care only about
#: the latest one arriving - there is no aggregate here to version.
_STREAM: Final[str] = "Maintenance-admission"

_AGGREGATE_ID: Final[str] = "admission"
_AGGREGATE_TYPE: Final[str] = "Maintenance"


class EventStoreAdmissionAnnouncer:
    """Writes :class:`AdmissionOpenEvent` to the event store.

    Satisfies ``syn_domain.contexts._shared.AdmissionAnnouncer``. Appends with
    ``ExpectedVersion.ANY``: two API replicas announcing at once is not a
    conflict to resolve, it is two true statements, and refusing one of them
    would be the failure this exists to prevent.
    """

    def __init__(self, event_store: EventStoreClient) -> None:
        self._event_store = event_store

    async def announce_open(self, mode: MaintenanceMode, *, after_restart: bool) -> None:
        """Append the announcement. Durable before it returns."""
        announced_at = datetime.now(UTC)
        envelope: EventEnvelope[DomainEvent] = EventEnvelope(
            event=AdmissionOpenEvent(
                announced_at=announced_at,
                reason=mode.reason,
                actor=mode.actor,
                after_restart=after_restart,
            ),
            metadata=EventMetadata(
                event_type=AdmissionOpenEvent.event_type,
                aggregate_id=_AGGREGATE_ID,
                aggregate_type=_AGGREGATE_TYPE,
                aggregate_nonce=0,
                timestamp=announced_at,
            ),
        )
        await self._event_store.append_events(
            stream_name=_STREAM,
            events=[envelope],
            expected_version=ExpectedVersion.ANY,
        )
