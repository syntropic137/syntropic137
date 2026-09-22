"""Bounded, revision-pinned inventory reads. Callers authorize every request."""

from __future__ import annotations

from typing import Literal, Protocol
from uuid import UUID  # noqa: TC003 - Pydantic resolves inherited InventoryModel fields at runtime

from pydantic import Field

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    CaptureReceipt,
    EvidenceRetraction,
    IdentityBinding,
    InventoryCoverage,
    InventoryGap,
    InventoryModel,
    InventoryNode,
    LineageEdge,
    Membership,
    RunIdentity,
)

InventoryItem = (
    InventoryNode
    | Membership
    | LineageEdge
    | CaptureReceipt
    | InventoryGap
    | EvidenceRetraction
    | IdentityBinding
)
ItemKind = Literal["node", "membership", "edge", "capture", "gap", "retraction", "binding"]


class InventoryCounts(InventoryModel):
    node: int = Field(ge=0)
    membership: int = Field(ge=0)
    edge: int = Field(ge=0)
    capture: int = Field(ge=0)
    gap: int = Field(ge=0)
    retraction: int = Field(default=0, ge=0)
    binding: int = Field(default=0, ge=0)


class InventorySnapshot(InventoryModel):
    snapshot_id: UUID
    run: RunIdentity
    revision: str
    resolver_version: str
    evidence_watermark: int = Field(ge=0)
    coverage: InventoryCoverage
    counts: InventoryCounts


class InventoryPage(InventoryModel):
    snapshot: InventorySnapshot
    kind: ItemKind
    items: tuple[InventoryItem, ...]
    next_after: int | None = Field(default=None, ge=0)


class SessionInventoryReadPort(Protocol):
    async def head(self, run: RunIdentity) -> InventorySnapshot | None: ...

    async def page(
        self,
        run: RunIdentity,
        snapshot_id: UUID,
        kind: ItemKind,
        *,
        after: int = -1,
        limit: int = 100,
    ) -> InventoryPage:
        """Reject absent/unpublished snapshots; never substitute the latest head."""
        ...
