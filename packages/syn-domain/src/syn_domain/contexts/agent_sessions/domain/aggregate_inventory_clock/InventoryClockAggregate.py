"""One immutable clock observation per stream; replay never schedules work."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from syn_domain.contexts.agent_sessions.domain.commands.ObserveInventoryClockCommand import (
        ObserveInventoryClockCommand,
    )


from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

from syn_domain.contexts.agent_sessions.domain.events.InventoryReconciliationSweepEvent import (
    InventoryReconciliationSweepEvent,
)


@aggregate("SessionInventoryClock")
class InventoryClockAggregate(AggregateRoot[InventoryReconciliationSweepEvent]):
    def __init__(self) -> None:
        super().__init__()
        self._observed_at: datetime | None = None

    def get_aggregate_type(self) -> str:
        return "SessionInventoryClock"

    @command_handler("ObserveInventoryClockCommand")
    def observe(self, command: ObserveInventoryClockCommand) -> None:
        if self._observed_at is not None and (
            self.id != command.aggregate_id or self._observed_at != command.observed_at
        ):
            raise ValueError("clock observation identity reused")
        if self._observed_at is not None:
            return
        self._initialize(command.aggregate_id)
        self._apply(InventoryReconciliationSweepEvent(observed_at=command.observed_at))

    @event_sourcing_handler("InventoryReconciliationSweep")
    def on_observed(self, event: InventoryReconciliationSweepEvent) -> None:
        self._observed_at = event.observed_at
