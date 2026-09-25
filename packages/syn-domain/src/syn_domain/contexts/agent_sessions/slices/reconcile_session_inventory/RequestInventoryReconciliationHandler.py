"""Durable scheduling boundary. Outbox acknowledgement follows successful save."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.domain.aggregate_inventory_reconciliation.InventoryReconciliationAggregate import (
    InventoryReconciliationAggregate,
)

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.commands.RequestInventoryReconciliationCommand import (
        RequestInventoryReconciliationCommand,
    )
    from syn_domain.repository import Repository


class RequestInventoryReconciliationHandler:
    def __init__(self, repository: Repository[InventoryReconciliationAggregate]) -> None:
        self._repository = repository

    async def handle(self, command: RequestInventoryReconciliationCommand) -> None:
        existing = await self._repository.get_by_id(command.aggregate_id)
        if existing is not None:
            existing.request(command)
            return
        aggregate = InventoryReconciliationAggregate()
        aggregate.request(command)
        await self._repository.save_new(aggregate)
