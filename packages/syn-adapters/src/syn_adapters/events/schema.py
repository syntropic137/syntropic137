"""Schema management for agent event store."""

from __future__ import annotations

import logging

import asyncpg

from syn_adapters.events.models import EXPECTED_COLUMNS

logger = logging.getLogger(__name__)


class SchemaValidationError(Exception):
    """Raised when database schema doesn't match expected schema."""

    pass


class EventStoreSchema:
    """Manages the agent_events table schema.

    Handles DDL creation, TimescaleDB hypertable setup, index creation,
    compression policies, and schema validation.

    Schema Management Strategy:
        Single Source of Truth: projection_stores/migrations/002_agent_events.sql

        The migration file defines the canonical schema. This Python code
        auto-creates the table as a fallback for development convenience,
        but the migration file is authoritative.

        To prevent schema drift:
        1. Always update the migration file FIRST when changing schema
        2. Run test_schema_consistency.py to verify Python matches SQL
        3. Update EXPECTED_COLUMNS in models.py to match
        4. Update docker/init-db if needed for fresh containers

        In production: Run migrations before deploying. Auto-creation is
        disabled when skip_auto_create=True.
    """

    def __init__(self, *, skip_auto_create: bool = False) -> None:
        self._skip_auto_create = skip_auto_create

    async def ensure_schema(self, conn: asyncpg.Connection) -> None:
        """Create schema if needed and validate it.

        Args:
            conn: Active database connection
        """
        # Enable TimescaleDB extension (always needed)
        await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")

        if not self._skip_auto_create:
            await self._create_table(conn)
            await self._create_indexes(conn)
            await self._configure_compression(conn)

        await self.validate(conn)

    async def _create_table(self, conn: asyncpg.Connection) -> None:
        """Create agent_events table and hypertable.

        Schema MUST match: projection_stores/migrations/002_agent_events.sql
        """
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_events (
                time TIMESTAMPTZ NOT NULL,
                event_type TEXT NOT NULL,
                session_id TEXT NOT NULL,
                execution_id TEXT,
                phase_id TEXT,
                data JSONB NOT NULL
            )
        """)

        # Create hypertable (partitioned by time)
        await conn.execute("""
            SELECT create_hypertable(
                'agent_events',
                'time',
                if_not_exists => TRUE,
                chunk_time_interval => INTERVAL '1 day'
            )
        """)

    async def _create_indexes(self, conn: asyncpg.Connection) -> None:
        """Create indexes for common queries."""
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_session
            ON agent_events (session_id, time DESC)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_execution
            ON agent_events (execution_id, time DESC)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_type
            ON agent_events (event_type, time DESC)
        """)

    async def _configure_compression(self, conn: asyncpg.Connection) -> None:
        """Configure TimescaleDB compression policies."""
        try:
            await conn.execute("""
                ALTER TABLE agent_events SET (
                    timescaledb.compress,
                    timescaledb.compress_segmentby = 'session_id',
                    timescaledb.compress_orderby = 'time DESC'
                )
            """)

            await conn.execute("""
                SELECT add_compression_policy(
                    'agent_events',
                    INTERVAL '1 day',
                    if_not_exists => TRUE
                )
            """)
        except asyncpg.PostgresError:
            # Compression might already be enabled
            pass

    async def validate(self, conn: asyncpg.Connection) -> None:
        """Validate that database schema matches expected columns.

        Raises:
            SchemaValidationError: If schema doesn't match
        """
        rows = await conn.fetch("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'agent_events'
            AND table_schema = 'public'
        """)

        actual_schema = {row["column_name"]: row["data_type"] for row in rows}

        mismatches = []
        for col, expected_type in EXPECTED_COLUMNS.items():
            actual_type = actual_schema.get(col)
            if actual_type is None:
                mismatches.append(f"Missing column: {col}")
            elif not actual_type.startswith(expected_type.split()[0]):
                # Partial match (e.g., "character varying" matches "character varying(100)")
                mismatches.append(f"Column {col}: expected '{expected_type}', got '{actual_type}'")

        if mismatches:
            msg = "Schema validation failed:\n  " + "\n  ".join(mismatches)
            logger.error(msg)
            raise SchemaValidationError(msg)
