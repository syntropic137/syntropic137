"""Owns reconstruction transitions. Infrastructure reports results, never next work."""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationRequest,
    ReconciliationStage,
    ReconciliationState,
)
from syn_domain.contexts.agent_sessions.domain.events.InventoryReconciliationChangedEvent import (
    InventoryReconciliationChangedEvent,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import RunIdentity

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.commands.AdvanceInventoryReconciliationCommand import (
        AdvanceInventoryReconciliationCommand,
    )
    from syn_domain.contexts.agent_sessions.domain.commands.RequestInventoryReconciliationCommand import (
        RequestInventoryReconciliationCommand,
    )


def _validate_result(
    state: ReconciliationState, command: AdvanceInventoryReconciliationCommand
) -> None:
    if command.stage is ReconciliationStage.FAILED:
        if command.failure_code is None:
            raise ValueError("failed reconciliation requires a failure code")
        return
    if command.failure_code is not None:
        raise ValueError("successful step cannot carry a failure")
    if command.revision is None:
        raise ValueError("publication requires a fully staged revision")
    if command.stage is ReconciliationStage.COMPLETED and command.revision != state.revision:
        raise ValueError("completion requires publication of the staged revision")


@aggregate("InventoryReconciliation")
class InventoryReconciliationAggregate(AggregateRoot[InventoryReconciliationChangedEvent]):
    _aggregate_type: str

    def __init__(self) -> None:
        super().__init__()
        self._state: ReconciliationState | None = None

    def get_aggregate_type(self) -> str:
        return self._aggregate_type

    @property
    def state(self) -> ReconciliationState | None:
        return self._state

    @command_handler("RequestInventoryReconciliationCommand")
    def request(self, command: RequestInventoryReconciliationCommand) -> None:
        if self._state is not None:
            if command.request != self._state.request or command.aggregate_id != str(self.id):
                raise ValueError("reconciliation idempotency key reused for different work")
            return
        self._initialize(command.aggregate_id)
        self._emit_state(ReconciliationState(request=command.request))

    @command_handler("AdvanceInventoryReconciliationCommand")
    def advance(self, command: AdvanceInventoryReconciliationCommand) -> None:
        state = self._state
        if state is None or command.aggregate_id != str(self.id):
            raise ValueError("unknown reconciliation")
        stage = command.stage
        if stage == state.stage:
            if command.revision != state.revision or command.failure_code != state.failure_code:
                raise ValueError("reconciliation step replay changed its result")
            return
        if state.stage in (ReconciliationStage.COMPLETED, ReconciliationStage.FAILED):
            raise ValueError("reconciliation is terminal")
        allowed = {
            ReconciliationStage.PENDING: {
                ReconciliationStage.PUBLISHING,
                ReconciliationStage.FAILED,
            },
            ReconciliationStage.PUBLISHING: {
                ReconciliationStage.COMPLETED,
                ReconciliationStage.FAILED,
            },
        }
        if stage not in allowed[state.stage]:
            raise ValueError("completion requires publication; cannot reset reconciliation")
        _validate_result(state, command)
        self._emit_state(
            ReconciliationState(
                request=state.request,
                stage=stage,
                revision=command.revision,
                failure_code=command.failure_code,
            )
        )

    def _emit_state(self, state: ReconciliationState) -> None:
        request = state.request
        self._apply(
            InventoryReconciliationChangedEvent(
                source_instance_id=request.run.source_instance_id,
                execution_id=request.run.execution_id,
                evidence_watermark=request.evidence_watermark,
                expected_head=request.expected_head,
                snapshot_id=request.snapshot_id,
                resolver_version=request.resolver_version,
                stage=state.stage.value,
                revision=state.revision,
                failure_code=state.failure_code,
            )
        )

    @event_sourcing_handler("InventoryReconciliationChanged")
    def on_changed(self, event: InventoryReconciliationChangedEvent) -> None:
        self._state = ReconciliationState(
            request=ReconciliationRequest(
                run=RunIdentity(
                    source_instance_id=event.source_instance_id, execution_id=event.execution_id
                ),
                evidence_watermark=event.evidence_watermark,
                expected_head=event.expected_head,
                snapshot_id=event.snapshot_id,
                resolver_version=event.resolver_version,
            ),
            stage=ReconciliationStage(event.stage),
            revision=event.revision,
            failure_code=event.failure_code,
        )
