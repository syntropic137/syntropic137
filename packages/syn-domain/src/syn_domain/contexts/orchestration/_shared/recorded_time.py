"""When an event was recorded, for projections that need it (#959).

An event payload carries no clock. ``WorkflowTemplateCreated`` has no
``created_at``, so a projection that read one from the payload stored ``None``
for every template and its ``-created_at`` sort ordered nothing. The time
exists, on the envelope: the store stamps ``recorded_time_unix_ms`` at commit.

``AutoDispatchProjection`` hands ``on_*`` handlers the payload only (#924), so
``RecordedTimeProjection`` keeps the envelope's ``recorded_timestamp`` for the
duration of one dispatch and exposes it as ``recorded_at``. A replay reads the
same envelope, so it gets the same time: never substitute ``now()``, which
would re-stamp history on every rebuild.

TODO(#924): delete once the pinned ESP passes ``envelope.metadata`` to a
handler that declares a second parameter, and read it there instead.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from event_sourcing import AutoDispatchProjection

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime

    from event_sourcing import (
        DispatchContext,
        DomainEvent,
        EventEnvelope,
        ProjectionCheckpointStore,
        ProjectionResult,
    )


class RecordedTimeProjection(AutoDispatchProjection):
    """An ``AutoDispatchProjection`` whose handlers can read ``recorded_at``."""

    _recorded_at: datetime | None = None

    @property
    def recorded_at(self) -> datetime | None:
        """When the event being handled was committed to the store (UTC).

        None only when a handler is called without an envelope at all, as a
        unit test calling ``on_*`` directly does; both dispatch paths
        (``handle_event`` and the legacy ``ProjectionManager``) set it.
        """
        return self._recorded_at

    @contextmanager
    def recording(self, envelope: EventEnvelope[DomainEvent]) -> Iterator[None]:
        """Expose ``envelope``'s recorded time to the handlers for one dispatch."""
        self._recorded_at = envelope.metadata.recorded_timestamp
        try:
            yield
        finally:
            self._recorded_at = None

    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: ProjectionCheckpointStore,
        context: DispatchContext | None = None,
    ) -> ProjectionResult:
        with self.recording(envelope):
            return await super().handle_event(envelope, checkpoint_store, context)
