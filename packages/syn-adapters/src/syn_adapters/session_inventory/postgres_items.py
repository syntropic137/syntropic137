"""Typed item codecs and immutable per-position writes within a locked snapshot."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import (
    CaptureReceipt,
    EvidenceRetraction,
    IdentityBinding,
    InventoryGap,
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
    await conn.execute(
        """INSERT INTO session_inventory_items
        (source_instance_id,execution_id,snapshot_id,kind,ordinal,payload)
        VALUES ($1,$2,$3,$4,$5,$6::jsonb)""",
        *args,
        item.model_dump_json(),
    )
