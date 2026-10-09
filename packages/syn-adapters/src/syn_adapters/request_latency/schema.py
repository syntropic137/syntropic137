"""The ``api_request_latency`` hypertable: one row per API request (ADR-073).

Lives in the observability database beside ``agent_events`` and follows the
same DDL policy: created here at startup unless ``SYN_SKIP_AUTO_CREATE_TABLES``
says the migrations own it, in which case only its presence is checked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

TABLE = "api_request_latency"
RETENTION_DAYS = 30
"""Raw rows older than this are dropped by TimescaleDB, a day-sized chunk at a time."""

_DDL = (
    f"""
    CREATE TABLE IF NOT EXISTS {TABLE} (
        time TIMESTAMPTZ NOT NULL,
        method TEXT NOT NULL,
        route TEXT NOT NULL,
        status SMALLINT NOT NULL,
        duration_ms DOUBLE PRECISION NOT NULL,
        request_id TEXT NOT NULL
    )
    """,
    f"""
    SELECT create_hypertable(
        '{TABLE}', 'time', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day'
    )
    """,
    f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_route_time ON {TABLE} (route, time DESC)",
    f"SELECT add_retention_policy('{TABLE}', INTERVAL '{RETENTION_DAYS} days', if_not_exists => TRUE)",
)


async def ensure_request_latency_schema(
    conn: asyncpg.Connection, *, skip_auto_create: bool
) -> bool:
    """Make the table ready; True when it exists afterwards.

    The timescaledb extension is created by the agent event schema, which runs
    first on the same database.
    """
    if not skip_auto_create:
        for statement in _DDL:
            await conn.execute(statement)
    found = await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", TABLE)
    return bool(found)
