"""Bounded, revision-pinned inventory reads. Callers authorize every request."""

from __future__ import annotations

from typing import Literal, Protocol
from uuid import UUID  # noqa: TC003 - Pydantic resolves inherited InventoryModel fields at runtime

from pydantic import Field

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    CaptureReceipt,
    EvidenceRetraction,
    Identifier,
    IdentityBinding,
    InventoryCoverage,
    InventoryGap,
    InventoryModel,
    InventoryNode,
    LineageEdge,
    Membership,
    ResolvedInventory,
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


class InventoryNamespaceCount(InventoryModel):
    """Distinct nodes in one identity namespace. Transcripts are split per harness."""

    kind: Literal["platform", "invocation", "transcript"]
    harness: Identifier | None = None
    count: int = Field(ge=0)


class InventoryCounts(InventoryModel):
    node: int = Field(ge=0)
    membership: int = Field(ge=0)
    edge: int = Field(ge=0)
    capture: int = Field(ge=0)
    gap: int = Field(ge=0)
    retraction: int = Field(default=0, ge=0)
    binding: int = Field(default=0, ge=0)
    namespaces: tuple[InventoryNamespaceCount, ...] | None = None
    """Distinct node counts per identity namespace; None on snapshots built before #1398 D."""


_NAMESPACE_ORDER = {"platform": 0, "invocation": 1, "transcript": 2}


def inventory_counts(resolved: ResolvedInventory) -> InventoryCounts:
    """The one place a snapshot's declared counts are derived from its resolved content."""
    tally: dict[tuple[Literal["platform", "invocation", "transcript"], str | None], int] = {}
    for node in resolved.nodes:
        slot = (node.ref.kind, node.ref.harness)
        tally[slot] = tally.get(slot, 0) + 1
    namespaces = tuple(
        InventoryNamespaceCount(kind=kind, harness=harness, count=count)
        for (kind, harness), count in sorted(
            tally.items(), key=lambda entry: (_NAMESPACE_ORDER[entry[0][0]], entry[0][1] or "")
        )
    )
    return InventoryCounts(
        node=len(resolved.nodes),
        binding=len(resolved.bindings),
        membership=len(resolved.memberships),
        edge=len(resolved.edges),
        capture=len(resolved.captures),
        gap=len(resolved.gaps),
        retraction=len(resolved.retractions),
        namespaces=namespaces,
    )


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


class InventoryFilter(InventoryModel):
    """Membership narrowing. Unset fields match every phase or attempt.

    A filter never changes what a node is; it selects nodes with at least one
    matching membership, the edges and bindings touching them, their captures,
    run-level or touching gaps, and every retraction (retractions are not
    node-scoped).
    """

    phase_id: Identifier | None = None
    attempt_id: Identifier | None = None

    @property
    def active(self) -> bool:
        return self.phase_id is not None or self.attempt_id is not None


class InventoryItemKeys(InventoryModel):
    """Qualified node keys an item references, so a foreign endpoint is resolvable."""

    node_key: str | None = None
    peer_key: str | None = None


class InventoryQueryPage(InventoryModel):
    """One filtered keyset page. ``last_ordinal`` is the resume key, never a count."""

    snapshot: InventorySnapshot
    kind: ItemKind
    filters: InventoryFilter
    items: tuple[InventoryItem, ...]
    item_keys: tuple[InventoryItemKeys, ...]
    last_ordinal: int | None = Field(default=None, ge=0)
    has_more: bool


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

    async def query(
        self,
        run: RunIdentity,
        snapshot_id: UUID,
        kind: ItemKind,
        *,
        filters: InventoryFilter,
        after: int = -1,
        limit: int = 100,
    ) -> InventoryQueryPage:
        """Bounded indexed keyset page of one published snapshot, narrowed in SQL."""
        ...

    async def node(
        self, run: RunIdentity, snapshot_id: UUID, node_key: str
    ) -> InventoryNode | None:
        """Resolve one node of a published snapshot; None when it is not in that revision."""
        ...
