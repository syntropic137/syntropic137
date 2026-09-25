"""Idempotently schedule reconstruction from an immutable input watermark."""

from event_sourcing import command

from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationRequest,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    Identifier,
    InventoryModel,
)


@command("RequestInventoryReconciliation", "Schedule workflow session reconstruction")
class RequestInventoryReconciliationCommand(InventoryModel):
    aggregate_id: Identifier
    request: ReconciliationRequest
