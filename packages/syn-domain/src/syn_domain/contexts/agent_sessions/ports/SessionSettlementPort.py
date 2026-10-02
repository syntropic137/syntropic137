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
    async def schedule(self, deadline: SettlementDeadline) -> SettlementDeadline:
        """Idempotent; returns the run's durable deadline.

        The first terminal fact wins and is immutable: later terminal facts and
        replays under a different grace setting get the stored record back.
        """
        ...

    async def observe_clock(self, observed_at: datetime) -> None:
        """To-do only: remember the latest RECORDED clock time (monotonic max).

        Safe during catch-up; it releases nothing.
        """
        ...

    async def due(self, *, limit: int) -> SettlementDeadlinePage:
        """Unsettled deadlines at or before the latest recorded clock time."""
        ...

    async def settle(self, deadline: SettlementDeadline) -> None:
        """Call only AFTER the deadline evidence batch is durable."""
        ...
