"""Schema management for agent event store."""

from __future__ import annotations

import logging

import asyncpg

from syn_shared.events import GIT_COMMIT

from syn_adapters.events.models import EXPECTED_COLUMNS

logger = logging.getLogger(__name__)

# The trigger that keeps agent_event_day_rollup in step with agent_events
# (#1253). `day` uses the SAME expression the heatmap buckets with, so the
# rollup's days are the heatmap's days by construction rather than by
# agreement between two pieces of code.
ROLLUP_TRIGGER_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION agent_event_day_rollup_apply() RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO agent_event_day_rollup (day, session_id, execution_id, first_time, commits)
    VALUES (
        time_bucket('1 day', NEW.time)::date,
        NEW.session_id,
        NEW.execution_id,
        NEW.time,
        CASE WHEN NEW.event_type = '{GIT_COMMIT}' THEN 1 ELSE 0 END
    )
    ON CONFLICT (day, session_id, (COALESCE(execution_id, ''))) DO UPDATE
    SET first_time = LEAST(agent_event_day_rollup.first_time, EXCLUDED.first_time),
        commits    = agent_event_day_rollup.commits + EXCLUDED.commits;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

# Idempotent: ON CONFLICT DO NOTHING makes a re-run a no-op rather than a
# double count.
ROLLUP_BACKFILL_SQL = f"""
INSERT INTO agent_event_day_rollup (day, session_id, execution_id, first_time, commits)
SELECT
    time_bucket('1 day', time)::date,
    session_id,
    execution_id,
    MIN(time),
    COUNT(*) FILTER (WHERE event_type = '{GIT_COMMIT}')
FROM agent_events
GROUP BY 1, 2, 3
ON CONFLICT (day, session_id, (COALESCE(execution_id, ''))) DO NOTHING;
"""


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
            await self._create_day_rollup(conn)

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

    async def _create_day_rollup(self, conn: asyncpg.Connection) -> None:
        """Create the per-day rollup that bounds the contribution heatmap (#1253).

        Schema MUST match:
        projection_stores/migrations/004_agent_event_day_rollup.sql - that file
        is authoritative and is what production runs. This is the same
        development-convenience fallback the table above gets.

        One transaction, deliberately: CREATE TRIGGER takes ACCESS EXCLUSIVE on
        agent_events, so the backfill sees exactly the rows the trigger did
        not. Split into separate statements there is a window in which an event
        is counted twice or not at all.
        """
        async with conn.transaction():
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_event_day_rollup (
                    day          DATE        NOT NULL,
                    session_id   TEXT        NOT NULL,
                    execution_id TEXT,
                    first_time   TIMESTAMPTZ NOT NULL,
                    commits      BIGINT      NOT NULL DEFAULT 0
                )
            """)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS agent_event_day_rollup_key
                ON agent_event_day_rollup (day, session_id, (COALESCE(execution_id, '')))
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rollup_session_day
                ON agent_event_day_rollup (session_id, day)
            """)
            await conn.execute(ROLLUP_TRIGGER_FUNCTION_SQL)
            await conn.execute("""
                DROP TRIGGER IF EXISTS agent_events_day_rollup ON agent_events
            """)
            await conn.execute("""
                CREATE TRIGGER agent_events_day_rollup
                AFTER INSERT ON agent_events
                FOR EACH ROW EXECUTE FUNCTION agent_event_day_rollup_apply()
            """)
            await conn.execute(ROLLUP_BACKFILL_SQL)

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
