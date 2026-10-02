"""Report one idempotent infrastructure step to the management aggregate."""

from event_sourcing import command

from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationStage,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    Identifier,
    InventoryModel,
)


@command("AdvanceInventoryReconciliation", "Report a session inventory reconciliation step")
class AdvanceInventoryReconciliationCommand(InventoryModel):
    aggregate_id: Identifier
    stage: ReconciliationStage
    revision: Identifier | None = None
    failure_code: Identifier | None = None
