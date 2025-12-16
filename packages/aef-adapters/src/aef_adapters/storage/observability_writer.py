"""
ObservabilityWriter for TimescaleDB.

Writes high-volume agent observations to a separate TimescaleDB hypertable
for optimal time-series performance and querying.

Architecture Decision: ADR-026 - TimescaleDB for Observability Storage
Pattern: Event Log + CQRS (ADR-018 Pattern 2)

This separates observability events (high-volume, time-series) from
domain events (low-volume, aggregate-centric) for scalability.
"""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import asyncpg


class ObservabilityWriter:
    """Write agent observations to TimescaleDB hypertable.

    This writer provides high-throughput, low-latency writes for
    agent telemetry data (token usage, tool calls, etc.).

    Performance: 2000+ observations/sec in testing.
    """

    def __init__(self, connection_string: str):
        """Initialize writer with connection string.

        Args:
            connection_string: PostgreSQL connection string for TimescaleDB
        """
        self.conn_string = connection_string
        self.pool: asyncpg.Pool | None = None
        self._initialized = False

    async def initialize(self):
        """Initialize connection pool and create schema.

        Creates:
        - TimescaleDB extension
        - agent_observations hypertable
        - Compression policies
        - Retention policies (future)
        """
        if self._initialized:
            return

        self.pool = await asyncpg.create_pool(self.conn_string, min_size=2, max_size=10)

        async with self.pool.acquire() as conn:
            # Enable TimescaleDB extension
            await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")

            # Create observations table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_observations (
                    time TIMESTAMPTZ NOT NULL,
                    session_id TEXT NOT NULL,
                    observation_type TEXT NOT NULL,
                    observation_id TEXT NOT NULL,
                    execution_id TEXT,
                    phase_id TEXT,
                    workspace_id TEXT,
                    data JSONB NOT NULL,
                    PRIMARY KEY (time, observation_id)
                )
            """)

            # Create hypertable (partitioned by time for time-series optimization)
            await conn.execute("""
                SELECT create_hypertable(
                    'agent_observations',
                    'time',
                    if_not_exists => TRUE,
                    chunk_time_interval => INTERVAL '1 day'
                )
            """)

            # Create indexes for common queries
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_observations_session
                ON agent_observations (session_id, time DESC)
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_observations_execution
                ON agent_observations (execution_id, time DESC)
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_observations_type
                ON agent_observations (observation_type, time DESC)
            """)

            # Configure compression (compress data older than 7 days)
            await conn.execute("""
                ALTER TABLE agent_observations SET (
                    timescaledb.compress,
                    timescaledb.compress_segmentby = 'session_id, observation_type'
                )
            """)

            # Add compression policy
            await conn.execute("""
                SELECT add_compression_policy(
                    'agent_observations',
                    INTERVAL '7 days',
                    if_not_exists => TRUE
                )
            """)

            # Add retention policy (optional - keep data for 90 days)
            # Uncomment when ready for production data lifecycle management
            # await conn.execute('''
            #     SELECT add_retention_policy(
            #         'agent_observations',
            #         INTERVAL '90 days',
            #         if_not_exists => TRUE
            #     )
            # ''')

        self._initialized = True

    async def record_observation(
        self,
        session_id: str,
        observation_type: str,
        data: dict[str, Any],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> str:
        """Record a single observation.

        Args:
            session_id: The session ID
            observation_type: Type of observation (token_usage, tool_started, tool_completed, etc.)
            data: Observation data (JSONB)
            execution_id: Optional execution ID
            phase_id: Optional phase ID
            workspace_id: Optional workspace ID

        Returns:
            The generated observation_id
        """
        if not self._initialized:
            await self.initialize()

        if self.pool is None:
            raise RuntimeError("ObservabilityWriter pool is not initialized")

        observation_id = str(uuid4())

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO agent_observations
                (time, session_id, observation_type, observation_id, data, execution_id, phase_id, workspace_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
                datetime.now(UTC),
                session_id,
                observation_type,
                observation_id,
                json.dumps(data),
                execution_id,
                phase_id,
                workspace_id,
            )

        return observation_id

    async def close(self):
        """Close connection pool."""
        if self.pool:
            await self.pool.close()
            self.pool = None
            self._initialized = False


# Singleton instance (lazy-loaded)
_observability_writer: ObservabilityWriter | None = None


def get_observability_writer(connection_string: str | None = None) -> ObservabilityWriter:
    """Get or create the ObservabilityWriter singleton.

    Args:
        connection_string: Optional connection string (uses settings if not provided)

    Returns:
        ObservabilityWriter instance
    """
    global _observability_writer

    if _observability_writer is None:
        if connection_string is None:
            from aef_shared.settings.config import get_settings

            settings = get_settings()
            connection_string = (
                f"postgresql://{settings.timescale_user}:{settings.timescale_password.get_secret_value()}"
                f"@{settings.timescale_host}:{settings.timescale_port}/{settings.timescale_db}"
            )

        _observability_writer = ObservabilityWriter(connection_string)

    return _observability_writer
