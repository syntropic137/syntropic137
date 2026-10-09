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
    _recorded_sequence: int | None = None

    @property
    def recorded_at(self) -> datetime | None:
        """When the event being handled was committed to the store (UTC).

        None only when a handler is called without an envelope at all, as a
        unit test calling ``on_*`` directly does; both dispatch paths
        (``handle_event`` and the legacy ``ProjectionManager``) set it.
        """
        return self._recorded_at

    @property
    def recorded_sequence(self) -> int | None:
        """The handled event's position in its own stream (``aggregate_nonce``).

        Immutable and unique per stream, so it identifies an event where a
        recorded time cannot: two events committed in one batch share a
        millisecond, and clocks can step backwards. None exactly when
        ``recorded_at`` is.
        """
        return self._recorded_sequence

    @contextmanager
    def recording(self, envelope: EventEnvelope[DomainEvent]) -> Iterator[None]:
        """Expose ``envelope``'s recorded time to the handlers for one dispatch."""
        self._recorded_at = envelope.metadata.recorded_timestamp
        self._recorded_sequence = envelope.metadata.aggregate_nonce
        try:
            yield
        finally:
            self._recorded_at = None
            self._recorded_sequence = None

    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: ProjectionCheckpointStore,
        context: DispatchContext | None = None,
    ) -> ProjectionResult:
        with self.recording(envelope):
            return await super().handle_event(envelope, checkpoint_store, context)
