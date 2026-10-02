"""Register or advance one controlled harness invocation."""

from event_sourcing import command

from syn_domain.contexts.agent_sessions._shared.session_invocation import SessionInvocationState
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    Identifier,
    InventoryModel,
)


@command("RecordSessionInvocation", "Durably register and track a controlled invocation")
class RecordSessionInvocationCommand(InventoryModel):
    aggregate_id: Identifier
    invocation: SessionInvocationState
