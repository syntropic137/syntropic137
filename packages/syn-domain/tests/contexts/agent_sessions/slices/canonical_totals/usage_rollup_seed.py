"""Shared plumbing for the usage-rollup database tests (#1558).

A throwaway database per test, the raw-row COPY the production writer uses,
and "the database as it stood before E1" (agent_events and the day rollup,
no usage rollup), which is where every backfill starts.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

import asyncpg

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable
    from datetime import datetime

COLUMNS = ("time", "event_type", "session_id", "execution_id", "phase_id", "data")


@dataclass(frozen=True)
class Row:
    """One agent_events row, as the writer COPYs it."""

    time: datetime
    event_type: str
    session_id: str
    execution_id: str | None
    data: str
    """The JSONB payload, already encoded."""
    phase_id: str = "p1"

    def record(self) -> tuple[datetime, str, str, str | None, str, str]:
        return (
            self.time,
            self.event_type,
            self.session_id,
            self.execution_id,
            self.phase_id,
            self.data,
        )


def _utc_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", "timezone=UTC", ""))


@asynccontextmanager
async def throwaway_database(admin_url: str) -> AsyncIterator[str]:
    """An empty database of its own, dropped afterwards."""
    name = f"usage_rollup_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(admin_url)
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    try:
        yield _utc_database(admin_url, name)
    finally:
        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        finally:
            await admin.close()


async def prepare_pre_e1_schema(dsn: str) -> None:
    """agent_events and the day rollup, and no usage rollup: a pre-E1 database."""
    from syn_adapters.events import AgentEventStore

    store = AgentEventStore(dsn)
    await store.initialize()
    try:
        assert store.pool is not None
        async with store.pool.acquire() as conn:
            await conn.execute("DROP TRIGGER IF EXISTS agent_events_usage_rollup ON agent_events")
            await conn.execute(
                "DROP TABLE IF EXISTS agent_summary_usage, agent_turn_usage_rollup, "
                "agent_usage_rollup_state"
            )
    finally:
        await store.close()


async def copy_rows(conn: asyncpg.Connection, rows: Iterable[Row]) -> None:
    """COPY, as AgentEventStore.insert_batch does, so triggers see real writes."""
    await conn.copy_records_to_table(
        "agent_events", records=[r.record() for r in rows], columns=COLUMNS
    )
