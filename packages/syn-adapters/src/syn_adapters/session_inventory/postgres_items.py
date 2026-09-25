"""Typed item codecs and immutable per-position writes within a locked snapshot."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, NamedTuple

from syn_domain.contexts.agent_sessions import (
    CaptureReceipt,
    EvidenceRetraction,
    IdentityBinding,
    InventoryGap,
    InventoryItemKeys,
    InventoryNode,
    InventoryPublicationConflict,
    LineageEdge,
    Membership,
)

if TYPE_CHECKING:
    from uuid import UUID

    from syn_domain.contexts.agent_sessions import InventoryItem, ItemKind, RunIdentity

    from .database import Connection

ITEM_MODELS = {
    "node": InventoryNode,
    "membership": Membership,
    "edge": LineageEdge,
    "capture": CaptureReceipt,
    "gap": InventoryGap,
    "retraction": EvidenceRetraction,
    "binding": IdentityBinding,
}


class QueryKeys(NamedTuple):
    """Hashed, bounded query columns. Raw opaque IDs stay only in the payload."""

    node_key: str | None
    peer_key: str | None
    phase_key: str | None
    attempt_key: str | None

    @property
    def item_keys(self) -> InventoryItemKeys:
        return InventoryItemKeys(node_key=self.node_key, peer_key=self.peer_key)


def filter_key(value: str | None) -> str | None:
    """Phase/attempt IDs may be 2048 chars; a digest keeps btree tuples bounded."""
    return None if value is None else hashlib.sha256(value.encode()).hexdigest()


def query_keys(item: InventoryItem) -> QueryKeys:
    if isinstance(item, InventoryNode):
        return QueryKeys(item.ref.key, None, None, None)
    if isinstance(item, Membership):
        return QueryKeys(
            item.node.key, None, filter_key(item.phase_id), filter_key(item.attempt_id)
        )
    if isinstance(item, CaptureReceipt):
        return QueryKeys(item.node.key, None, None, None)
    if isinstance(item, LineageEdge):
        return QueryKeys(item.parent.key, item.child.key, None, None)
    if isinstance(item, IdentityBinding):
        return QueryKeys(item.owner.key, item.transcript.key, None, None)
    return QueryKeys(None, None, None, None)


async def append_item(
    conn: Connection,
    run: RunIdentity,
    snapshot_id: UUID,
    kind: ItemKind,
    ordinal: int,
    item: InventoryItem,
    *,
    published: bool,
) -> None:
    args = (run.source_instance_id, run.execution_id, snapshot_id, kind, ordinal)
    prior = await conn.fetchval(
        """SELECT payload::text FROM session_inventory_items
        WHERE source_instance_id=$1 AND execution_id=$2 AND snapshot_id=$3 AND kind=$4 AND ordinal=$5""",
        *args,
    )
    if prior is not None:
        if ITEM_MODELS[kind].model_validate_json(prior) != item:
            raise InventoryPublicationConflict("immutable inventory item changed")
        return
    if published:
        raise InventoryPublicationConflict("published snapshot is immutable")
    keys = query_keys(item)
    await conn.execute(
        """INSERT INTO session_inventory_items
        (source_instance_id,execution_id,snapshot_id,kind,ordinal,payload,
        node_key,peer_key,phase_key,attempt_key,keys_indexed)
        VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,$10,TRUE)""",
        *args,
        item.model_dump_json(),
        *keys,
    )
