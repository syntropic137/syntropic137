"""Publication transaction. A competing writer cannot overwrite a newer head."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from syn_domain.contexts.agent_sessions import (
    InventoryNotFound,
    InventoryPublicationConflict,
    InventorySnapshot,
    NamespaceKey,
    RunIdentity,
    namespace_counts,
)

if TYPE_CHECKING:
    from uuid import UUID

    from .database import Connection


async def publish_snapshot(
    conn: Connection, run: RunIdentity, snapshot_id: UUID, expected_head: UUID | None
) -> None:
    args = (run.source_instance_id, run.execution_id)
    await conn.execute(
        """INSERT INTO session_inventory_heads (source_instance_id,execution_id)
        VALUES ($1,$2) ON CONFLICT DO NOTHING""",
        *args,
    )
    current = await conn.fetchval(
        """SELECT snapshot_id::text FROM session_inventory_heads
        WHERE source_instance_id=$1 AND execution_id=$2 FOR UPDATE""",
        *args,
    )
    if current == str(snapshot_id):
        return  # Retry after a committed response was lost.
    if current != (str(expected_head) if expected_head is not None else None):
        raise InventoryPublicationConflict("inventory head changed during reconciliation")
    raw = await conn.fetchval(
        """SELECT metadata::text FROM session_inventory_snapshots
        WHERE source_instance_id=$1 AND execution_id=$2 AND snapshot_id=$3
        AND NOT published FOR UPDATE""",
        *args,
        snapshot_id,
    )
    if raw is None:
        raise InventoryNotFound("no unpublished snapshot in this run")
    snapshot = InventorySnapshot.model_validate_json(raw)
    await _validate_snapshot_complete(conn, run, snapshot_id, snapshot)
    if snapshot.counts.namespaces is None:
        snapshot = await _complete_derived_counts(conn, run, snapshot)
    counts = snapshot.counts
    sequence = 1
    if expected_head is not None:
        previous = await conn.fetchval(
            """SELECT revision_sequence::text FROM session_inventory_publications
            WHERE source_instance_id=$1 AND execution_id=$2 AND snapshot_id=$3""",
            *args,
            expected_head,
        )
        if previous is None:
            raise InventoryPublicationConflict("published head has no durable publication order")
        sequence = int(previous) + 1
    record_count = sum(
        (
            counts.node,
            counts.membership,
            counts.edge,
            counts.capture,
            counts.gap,
            counts.retraction,
            counts.binding,
        )
    )
    high = await conn.fetchval(
        """INSERT INTO session_inventory_replication_sequences AS s
        (source_instance_id,high_watermark) VALUES ($1,$2)
        ON CONFLICT (source_instance_id) DO UPDATE
        SET high_watermark=s.high_watermark+EXCLUDED.high_watermark
        RETURNING high_watermark::text""",
        run.source_instance_id,
        record_count,
    )
    if high is None:
        raise InventoryPublicationConflict("replication sequence reservation failed")
    high_watermark = int(high)
    await conn.execute(
        """INSERT INTO session_inventory_publications
        (source_instance_id,execution_id,snapshot_id,parent_snapshot_id,revision_sequence,
        first_record_sequence,record_high_watermark)
        VALUES ($1,$2,$3,$4,$5,$6,$7)""",
        *args,
        snapshot_id,
        expected_head,
        sequence,
        high_watermark - record_count + 1,
        high_watermark,
    )
    await conn.execute(
        """UPDATE session_inventory_snapshots SET published=TRUE
        WHERE source_instance_id=$1 AND execution_id=$2 AND snapshot_id=$3""",
        *args,
        snapshot_id,
    )
    await conn.execute(
        """UPDATE session_inventory_heads SET snapshot_id=$3,evidence_watermark=$4
        WHERE source_instance_id=$1 AND execution_id=$2""",
        *args,
        snapshot_id,
        snapshot.evidence_watermark,
    )


_NODE_KINDS: dict[str, Literal["platform", "invocation", "transcript"]] = {
    "platform": "platform",
    "invocation": "invocation",
    "transcript": "transcript",
}


async def _complete_derived_counts(
    conn: Connection, run: RunIdentity, snapshot: InventorySnapshot
) -> InventorySnapshot:
    """Derive namespace counts for a revision staged before they were recorded.

    Deterministic: computed from the snapshot's own immutable node items, which
    the caller has just proven complete, so the revision is unchanged.
    """
    rows = await conn.fetch(
        """SELECT payload->'ref'->>'kind' AS kind, payload->'ref'->>'harness' AS harness,
        count(*)::text AS n FROM session_inventory_items
        WHERE source_instance_id=$1 AND execution_id=$2 AND snapshot_id=$3 AND kind='node'
        GROUP BY 1,2""",
        run.source_instance_id,
        run.execution_id,
        snapshot.snapshot_id,
    )
    tally: dict[NamespaceKey, int] = {}
    for row in rows:
        kind = _NODE_KINDS.get(row["kind"])
        if kind is None:
            raise InventoryPublicationConflict("stored node has an unknown identity kind")
        tally[(kind, row["harness"])] = int(row["n"])
    completed = snapshot.model_copy(
        update={
            "counts": snapshot.counts.model_copy(update={"namespaces": namespace_counts(tally)})
        }
    )
    # Re-validate: model_copy skips validation, and the stored form must round-trip.
    completed = InventorySnapshot.model_validate_json(completed.model_dump_json())
    await conn.execute(
        """UPDATE session_inventory_snapshots SET metadata=$4::jsonb
        WHERE source_instance_id=$1 AND execution_id=$2 AND snapshot_id=$3 AND NOT published""",
        run.source_instance_id,
        run.execution_id,
        snapshot.snapshot_id,
        completed.model_dump_json(),
    )
    return completed


async def _validate_snapshot_complete(
    conn: Connection, run: RunIdentity, snapshot_id: UUID, snapshot: InventorySnapshot
) -> None:
    """Reject stale evidence or missing batches while the publication lock is held."""
    args = (run.source_instance_id, run.execution_id)
    watermark = await conn.fetchval(
        """SELECT evidence_watermark::text FROM session_inventory_heads
        WHERE source_instance_id=$1 AND execution_id=$2""",
        *args,
    )
    if watermark is None or snapshot.evidence_watermark < int(watermark):
        raise InventoryPublicationConflict("input evidence predates the published head")
    counts = snapshot.counts
    for kind, expected in (
        ("node", counts.node),
        ("membership", counts.membership),
        ("edge", counts.edge),
        ("capture", counts.capture),
        ("gap", counts.gap),
        ("retraction", counts.retraction),
        ("binding", counts.binding),
    ):
        count = await conn.fetchval(
            """SELECT count(*)::text FROM session_inventory_items
            WHERE source_instance_id=$1 AND execution_id=$2 AND snapshot_id=$3 AND kind=$4""",
            *args,
            snapshot_id,
            kind,
        )
        if count is None or int(count) != expected:
            raise InventoryPublicationConflict("snapshot still has uncommitted batches")
