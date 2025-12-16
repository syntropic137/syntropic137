#!/usr/bin/env python3
"""
Standalone ObservabilityWriter for TimescaleDB.
This is a proof-of-concept implementation to validate the observability architecture.
"""
import json
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg


class ObservabilityWriter:
    """Write agent observations to TimescaleDB hypertable."""

    def __init__(self, connection_string: str):
        self.conn_string = connection_string
        self.pool = None

    async def initialize(self):
        """Initialize connection pool and create schema."""
        self.pool = await asyncpg.create_pool(self.conn_string)

        # Create schema
        async with self.pool.acquire() as conn:
            # Enable TimescaleDB extension
            await conn.execute('CREATE EXTENSION IF NOT EXISTS timescaledb;')

            # Create observations table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS agent_observations (
                    time TIMESTAMPTZ NOT NULL,
                    session_id TEXT NOT NULL,
                    observation_type TEXT NOT NULL,
                    observation_id TEXT NOT NULL,
                    execution_id TEXT,
                    data JSONB NOT NULL,
                    PRIMARY KEY (time, observation_id)
                )
            ''')

            # Create hypertable
            await conn.execute(
                "SELECT create_hypertable('agent_observations', 'time', if_not_exists => TRUE)"
            )

            # Configure compression
            await conn.execute('''
                ALTER TABLE agent_observations SET (
                    timescaledb.compress,
                    timescaledb.compress_segmentby = 'session_id, observation_type'
                )
            ''')

            # Add compression policy (compress data older than 7 days)
            await conn.execute('''
                SELECT add_compression_policy('agent_observations',
                    INTERVAL '7 days',
                    if_not_exists => TRUE
                )
            ''')

    async def record_observation(
        self,
        session_id: str,
        observation_type: str,
        data: dict,
        execution_id: str | None = None,
    ):
        """Record a single observation."""
        observation_id = str(uuid4())

        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO agent_observations
                (time, session_id, observation_type, observation_id, data, execution_id)
                VALUES ($1, $2, $3, $4, $5, $6)
            ''', datetime.now(UTC), session_id, observation_type,
                 observation_id, json.dumps(data), execution_id)

    async def close(self):
        """Close connection pool."""
        if self.pool:
            await self.pool.close()
