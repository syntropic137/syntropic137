"""Durable, replayable to-do records and fenced claims for reconstruction."""

from __future__ import annotations

from typing import Protocol

from pydantic import Field

from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationState,  # noqa: TC001 - runtime Pydantic field
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    InventoryModel,
    RoutingIdentifier,
    RunIdentity,
)


class InventoryJob(InventoryModel):
    job_id: RoutingIdentifier
    state: ReconciliationState
    global_position: int = Field(ge=0)


class InventoryJobLease(InventoryModel):
    job: InventoryJob
    token: int = Field(ge=1)


class InventoryLeaseLost(Exception):
    """Work must stop; another worker or a later projection owns this job."""


class SessionInventoryJobPort(Protocol):
    async def project(self, job: InventoryJob) -> None: ...
    async def get(self, job_id: str) -> InventoryJob | None: ...
    async def find_ids(self, source_instance_id: str, prefix: str) -> tuple[str, ...]:
        """Return at most two matching IDs; two means ambiguous. Exact match wins."""
        ...

    async def latest(self, run: RunIdentity) -> InventoryJob | None: ...
    async def claim(self, *, lease_seconds: int) -> InventoryJobLease | None: ...
    async def renew(self, lease: InventoryJobLease, *, lease_seconds: int) -> None: ...
    async def release(self, lease: InventoryJobLease, *, retry_seconds: int) -> None: ...
    async def publish(self, lease: InventoryJobLease) -> None:
        """Check lease and swap the inventory head in the same SQL transaction."""
        ...
