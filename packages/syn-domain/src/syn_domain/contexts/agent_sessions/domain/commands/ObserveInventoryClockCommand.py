"""Record one observed recovery-clock tick."""

from datetime import datetime

from event_sourcing import command

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    Identifier,
    InventoryModel,
)


@command("ObserveInventoryClock", "Record passage of time for inventory recovery")
class ObserveInventoryClockCommand(InventoryModel):
    aggregate_id: Identifier
    observed_at: datetime
