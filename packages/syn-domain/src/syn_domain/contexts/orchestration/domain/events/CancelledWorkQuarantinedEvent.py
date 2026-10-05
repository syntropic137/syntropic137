"""CancelledWorkQuarantined event - a cancelled run's unpushed work landed (#1547)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event

# Runtime import needed for the Pydantic field type (noqa: TC001)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    QuarantinedRef,  # noqa: TC001
)


@event("CancelledWorkQuarantined", "v1")
class CancelledWorkQuarantinedEvent(DomainEvent):
    """The cancelled phase's unpushed work that LANDED on a quarantine ref.

    A cancellation is recorded the moment it is asked for, by
    `ExecutionCancelled`, which is before the cancelled phase's workspace is
    saved and torn down - so that event cannot carry what the save found.
    This is the later fact, written once the save has run, and only when it
    landed something: the cancellation counterpart of
    `WorkflowFailed.quarantined_refs`, read by `QuarantineNoticeProcessManager`.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    quarantined_at: datetime
    quarantined_refs: list[QuarantinedRef]
