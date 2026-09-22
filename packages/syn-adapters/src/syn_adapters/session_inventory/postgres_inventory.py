"""Indexed, immutable inventory snapshots with atomic head publication (#1398)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import (
    InventoryItem,
    InventoryNotFound,
    InventoryPage,
    InventoryPublicationConflict,
    InventorySnapshot,
    ItemKind,
    RunIdentity,
)

from .postgres_items import ITEM_MODELS, append_item
from .postgres_publication import publish_snapshot

if TYPE_CHECKING:
    from uuid import UUID

    from .database import Pool

_SCOPE = "source_instance_id=$1 AND execution_id=$2 AND snapshot_id=$3"


class PostgresSessionInventory:
    """No remote I/O and no reconstruction on GET. Authorization lives above this port."""

    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def ensure_ready(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(Path(__file__).with_name("schema.sql").read_text())

    async def stage(self, snapshot: InventorySnapshot) -> None:
        run = snapshot.run
        async with self._pool.acquire() as conn:
            actual = await conn.fetchval(
                """INSERT INTO session_inventory_snapshots AS s
                (source_instance_id,execution_id,snapshot_id,metadata)
                VALUES ($1,$2,$3,$4::jsonb)
                ON CONFLICT (source_instance_id,execution_id,snapshot_id)
                DO UPDATE SET metadata=s.metadata
                RETURNING metadata::text""",
                run.source_instance_id,
                run.execution_id,
                snapshot.snapshot_id,
                snapshot.model_dump_json(),
            )
            if actual is None or InventorySnapshot.model_validate_json(actual) != snapshot:
                raise InventoryPublicationConflict(
                    "snapshot identity reused with different metadata"
                )

    async def append(
        self,
        run: RunIdentity,
        snapshot_id: UUID,
        kind: ItemKind,
        start: int,
        items: tuple[InventoryItem, ...],
    ) -> None:
        if start < 0 or not 1 <= len(items) <= 500:
            raise ValueError("batch must have 1..500 items and a nonnegative start")
        model = ITEM_MODELS[kind]
        if any(not isinstance(item, model) for item in items):
            raise ValueError("item does not match the requested inventory kind")
        args = (run.source_instance_id, run.execution_id, snapshot_id)
        async with self._pool.acquire() as conn, conn.transaction():
            # The row lock serializes append batches against publication.
            metadata = await conn.fetchval(
                f"SELECT metadata::text FROM session_inventory_snapshots WHERE {_SCOPE} FOR UPDATE",
                *args,
            )
            if metadata is None:
                raise InventoryNotFound("unknown staged snapshot")
            snapshot = InventorySnapshot.model_validate_json(metadata)
            if start + len(items) > getattr(snapshot.counts, kind):
                raise ValueError("batch exceeds declared snapshot size")
            published = await conn.fetchval(
                f"SELECT published::text FROM session_inventory_snapshots WHERE {_SCOPE}", *args
            )
            for offset, item in enumerate(items, start):
                await append_item(
                    conn, run, snapshot_id, kind, offset, item, published=published == "true"
                )

    async def publish(
        self, run: RunIdentity, snapshot_id: UUID, expected_head: UUID | None
    ) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            await publish_snapshot(conn, run, snapshot_id, expected_head)

    async def head(self, run: RunIdentity) -> InventorySnapshot | None:
        async with self._pool.acquire() as conn:
            raw = await conn.fetchval(
                """SELECT s.metadata::text FROM session_inventory_heads h
                JOIN session_inventory_snapshots s USING (source_instance_id,execution_id,snapshot_id)
                WHERE h.source_instance_id=$1 AND h.execution_id=$2 AND s.published""",
                run.source_instance_id,
                run.execution_id,
            )
        return None if raw is None else InventorySnapshot.model_validate_json(raw)

    async def page(
        self,
        run: RunIdentity,
        snapshot_id: UUID,
        kind: ItemKind,
        *,
        after: int = -1,
        limit: int = 100,
    ) -> InventoryPage:
        if after < -1 or not 1 <= limit <= 500:
            raise ValueError("page limit must be 1..500; cursor must be >= -1")
        args = (run.source_instance_id, run.execution_id, snapshot_id)
        async with self._pool.acquire() as conn:
            raw = await conn.fetchval(
                f"SELECT metadata::text FROM session_inventory_snapshots WHERE {_SCOPE} AND published",
                *args,
            )
            if raw is None:
                raise InventoryNotFound("no published snapshot in this run")
            rows = await conn.fetch(
                f"SELECT ordinal::text,payload::text FROM session_inventory_items WHERE {_SCOPE} "
                "AND kind=$4 AND ordinal>$5 ORDER BY session_inventory_items.ordinal LIMIT $6",
                *args,
                kind,
                after,
                limit + 1,
            )
        visible = rows[:limit]
        return InventoryPage(
            snapshot=InventorySnapshot.model_validate_json(raw),
            kind=kind,
            items=tuple(ITEM_MODELS[kind].model_validate_json(row["payload"]) for row in visible),
            next_after=int(visible[-1]["ordinal"]) if len(rows) > limit else None,
        )
