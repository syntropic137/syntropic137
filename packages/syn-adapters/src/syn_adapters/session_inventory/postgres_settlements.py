"""Durable settlement deadlines; replaying the same facts converges on one row."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import SettlementDeadline, SettlementDeadlinePage

if TYPE_CHECKING:
    from datetime import datetime

    from .database import Pool


class PostgresSettlementDeadlines:
    def __init__(self, pool: Pool, source_instance_id: str) -> None:
        self._pool = pool
        self._source = source_instance_id

    def _own(self, deadline: SettlementDeadline) -> None:
        if deadline.run.source_instance_id != self._source:
            raise ValueError("Settlement deadline belongs to another installation")

    async def schedule(self, deadline: SettlementDeadline) -> SettlementDeadline:
        self._own(deadline)
        async with self._pool.acquire() as conn, conn.transaction():
            # First terminal fact wins; a later one or another grace setting
            # never moves it. The stored record is the answer.
            await conn.execute(
                """INSERT INTO session_settlement_deadlines
                (source_instance_id,execution_id,due_at,payload)
                VALUES ($1,$2,$3,$4::jsonb) ON CONFLICT DO NOTHING""",
                deadline.run.source_instance_id,
                deadline.run.execution_id,
                deadline.due_at,
                deadline.model_dump_json(),
            )
            raw = await conn.fetchval(
                """SELECT payload::text FROM session_settlement_deadlines
                WHERE source_instance_id=$1 AND execution_id=$2""",
                deadline.run.source_instance_id,
                deadline.run.execution_id,
            )
        if raw is None:
            raise RuntimeError("settlement deadline vanished after scheduling")
        return SettlementDeadline.model_validate_json(raw)

    async def observe_clock(self, observed_at: datetime) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO session_settlement_clock (source_instance_id,observed_at)
                VALUES ($1,$2) ON CONFLICT (source_instance_id) DO UPDATE
                SET observed_at=GREATEST(session_settlement_clock.observed_at,EXCLUDED.observed_at)""",
                self._source,
                observed_at,
            )

    async def due(self, *, limit: int) -> SettlementDeadlinePage:
        if not 1 <= limit <= 500:
            raise ValueError("invalid settlement page bound")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT d.payload::text FROM session_settlement_deadlines d
                JOIN session_settlement_clock c ON c.source_instance_id=d.source_instance_id
                WHERE d.source_instance_id=$1 AND NOT d.settled AND d.due_at<=c.observed_at
                ORDER BY d.due_at,d.execution_id LIMIT $2""",
                self._source,
                limit,
            )
        return SettlementDeadlinePage(
            items=tuple(SettlementDeadline.model_validate_json(row["payload"]) for row in rows)
        )

    async def settle(self, deadline: SettlementDeadline) -> None:
        self._own(deadline)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE session_settlement_deadlines SET settled=TRUE
                WHERE source_instance_id=$1 AND execution_id=$2""",
                deadline.run.source_instance_id,
                deadline.run.execution_id,
            )
