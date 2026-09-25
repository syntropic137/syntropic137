"""Durable passage-of-time to-do for the bounded coverage settlement deadline (#1364)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - runtime Pydantic field
from typing import Protocol

from pydantic import Field

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    EvidenceReference,
    InventoryModel,
    RunIdentity,
)


class SettlementDeadline(InventoryModel):
    """First terminal fact for a run plus the grace the host granted it."""

    run: RunIdentity
    due_at: datetime
    terminal: EvidenceReference


class SettlementDeadlinePage(InventoryModel):
    items: tuple[SettlementDeadline, ...] = Field(max_length=500)


class SessionSettlementPort(Protocol):
    async def schedule(self, deadline: SettlementDeadline) -> None:
        """Idempotent. The first terminal fact wins; later ones never extend it."""
        ...

    async def due(self, observed_at: datetime, *, limit: int) -> SettlementDeadlinePage:
        """Unsettled deadlines at or before a recorded clock observation."""
        ...

    async def settle(self, deadline: SettlementDeadline) -> None:
        """Call only AFTER the deadline evidence batch is durable."""
        ...
