"""Filtered keyset reads of one published snapshot (#1398 row 8).

Every statement is bounded by LIMIT and served by the item primary key or the
hashed partial indexes in schema.sql. Membership narrowing happens in SQL;
nothing loads a whole snapshot and filters in Python.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from syn_domain.contexts.agent_sessions import (
    InventoryItemKeys,
    InventoryNode,
    InventoryNotFound,
    InventoryQueryPage,
    InventorySnapshot,
)

from .postgres_items import ITEM_MODELS, filter_key, query_keys

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import InventoryFilter, ItemKind, RunIdentity

    from .database import Connection, Pool

_SCOPE = "i.source_instance_id=$1 AND i.execution_id=$2 AND i.snapshot_id=$3"
_BACKFILL_BATCH = 500


def _member(column: str, phase: str | None, attempt: str | None) -> str:
    """Semi-join against matching membership rows, served by member_node_idx."""
    conditions = [
        "m.source_instance_id=i.source_instance_id",
        "m.execution_id=i.execution_id",
        "m.snapshot_id=i.snapshot_id",
        "m.kind='membership'",
        f"m.node_key={column}",
    ]
    if phase is not None:
        conditions.append(f"m.phase_key={phase}")
    if attempt is not None:
        conditions.append(f"m.attempt_key={attempt}")
    return f"EXISTS (SELECT 1 FROM session_inventory_items m WHERE {' AND '.join(conditions)})"


def _placeholders(filters: InventoryFilter) -> tuple[str | None, str | None, tuple[str, ...]]:
    """Digest parameters for the set filters, numbered from $7."""
    params = tuple(
        digest
        for digest in (filter_key(filters.phase_id), filter_key(filters.attempt_id))
        if digest is not None
    )
    phase = "$7" if filters.phase_id is not None else None
    attempt = None
    if filters.attempt_id is not None:
        attempt = "$8" if phase is not None else "$7"
    return phase, attempt, params


def _kind_predicate(kind: ItemKind, phase: str | None, attempt: str | None) -> str | None:
    """None means the section is not node-scoped and is never narrowed."""
    if kind == "membership":
        parts = [f"i.phase_key={phase}"] if phase else []
        return " AND ".join([*parts, *([f"i.attempt_key={attempt}"] if attempt else [])])
    if kind in ("node", "capture"):
        return _member("i.node_key", phase, attempt)
    if kind in ("edge", "binding"):
        return (
            f"({_member('i.node_key', phase, attempt)} OR {_member('i.peer_key', phase, attempt)})"
        )
    if kind == "gap":
        # Run-level gaps (no node keys) stay visible under every filter.
        return (
            "(jsonb_array_length(i.payload->'node_keys')=0 OR EXISTS (SELECT 1 FROM "
            "jsonb_array_elements_text(i.payload->'node_keys') AS k(key) "
            f"WHERE {_member('k.key', phase, attempt)}))"
        )
    return None  # Retractions correct evidence, not nodes; never hide them.


def narrowing_predicate(kind: ItemKind, filters: InventoryFilter) -> tuple[str, tuple[str, ...]]:
    """SQL predicate plus its parameters, numbered from $7."""
    if not filters.active:
        return "TRUE", ()
    phase, attempt, params = _placeholders(filters)
    predicate = _kind_predicate(kind, phase, attempt)
    return ("TRUE", ()) if predicate is None else (predicate, params)


def page_sql(kind: ItemKind, filters: InventoryFilter) -> tuple[str, tuple[str, ...]]:
    predicate, params = narrowing_predicate(kind, filters)
    return (
        "SELECT i.ordinal::text AS ordinal,i.payload::text AS payload,"
        "i.node_key,i.peer_key FROM session_inventory_items i "
        f"WHERE {_SCOPE} AND i.kind=$4 AND i.ordinal>$5 AND {predicate} "
        "ORDER BY i.ordinal LIMIT $6",
        params,
    )


async def _published(conn: Connection, run: RunIdentity, snapshot_id: UUID) -> InventorySnapshot:
    raw = await conn.fetchval(
        """SELECT metadata::text FROM session_inventory_snapshots
        WHERE source_instance_id=$1 AND execution_id=$2 AND snapshot_id=$3 AND published""",
        run.source_instance_id,
        run.execution_id,
        snapshot_id,
    )
    if raw is None:
        raise InventoryNotFound("no published snapshot in this run")
    return InventorySnapshot.model_validate_json(raw)


async def query_page(
    pool: Pool,
    run: RunIdentity,
    snapshot_id: UUID,
    kind: ItemKind,
    *,
    filters: InventoryFilter,
    after: int,
    limit: int,
) -> InventoryQueryPage:
    if after < -1 or not 1 <= limit <= 500:
        raise ValueError("page limit must be 1..500; cursor must be >= -1")
    sql, params = page_sql(kind, filters)
    async with pool.acquire() as conn:
        snapshot = await _published(conn, run, snapshot_id)
        rows = await conn.fetch(
            sql,
            run.source_instance_id,
            run.execution_id,
            snapshot_id,
            kind,
            after,
            limit + 1,
            *params,
        )
    visible = rows[:limit]
    return InventoryQueryPage(
        snapshot=snapshot,
        kind=kind,
        filters=filters,
        items=tuple(ITEM_MODELS[kind].model_validate_json(row["payload"]) for row in visible),
        item_keys=tuple(
            InventoryItemKeys(node_key=row["node_key"], peer_key=row["peer_key"]) for row in visible
        ),
        last_ordinal=int(visible[-1]["ordinal"]) if visible else None,
        has_more=len(rows) > limit,
    )


async def lookup_node(
    pool: Pool, run: RunIdentity, snapshot_id: UUID, node_key: str
) -> InventoryNode | None:
    async with pool.acquire() as conn:
        await _published(conn, run, snapshot_id)
        raw = await conn.fetchval(
            f"""SELECT i.payload::text FROM session_inventory_items i
            WHERE {_SCOPE} AND i.kind='node' AND i.node_key=$4 LIMIT 1""",
            run.source_instance_id,
            run.execution_id,
            snapshot_id,
            node_key,
        )
    return None if raw is None else InventoryNode.model_validate_json(raw)


async def backfill_query_keys(pool: Pool) -> int:
    """Index rows written before the query columns existed. Idempotent and batched."""
    total = 0
    while True:
        async with pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(
                """SELECT source_instance_id,execution_id,snapshot_id::text AS snapshot_id,
                kind,ordinal::text AS ordinal,payload::text AS payload
                FROM session_inventory_items WHERE NOT keys_indexed
                ORDER BY source_instance_id,execution_id,snapshot_id,kind,ordinal
                LIMIT $1 FOR UPDATE SKIP LOCKED""",
                _BACKFILL_BATCH,
            )
            for row in rows:
                kind = row["kind"]
                keys = query_keys(ITEM_MODELS[kind].model_validate_json(row["payload"]))
                await conn.execute(
                    """UPDATE session_inventory_items SET node_key=$6,peer_key=$7,
                    phase_key=$8,attempt_key=$9,keys_indexed=TRUE
                    WHERE source_instance_id=$1 AND execution_id=$2 AND snapshot_id=$3
                    AND kind=$4 AND ordinal=$5""",
                    row["source_instance_id"],
                    row["execution_id"],
                    UUID(row["snapshot_id"]),
                    kind,
                    int(row["ordinal"]),
                    *keys,
                )
        total += len(rows)
        if len(rows) < _BACKFILL_BATCH:
            return total
