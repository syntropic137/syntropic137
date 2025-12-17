#!/usr/bin/env python3
"""
Standalone CostProjection for TimescaleDB.
This is a proof-of-concept implementation to validate cost calculation from observations.
"""

from decimal import Decimal

import asyncpg


class CostProjection:
    """Calculate costs from agent observations stored in TimescaleDB."""

    def __init__(self, connection_string: str):
        self.conn_string = connection_string
        self.pool = None

    async def initialize(self):
        """Initialize connection pool."""
        self.pool = await asyncpg.create_pool(self.conn_string)

    async def calculate_session_cost(self, session_id: str) -> dict:
        """Calculate total cost for a session based on token usage and tool calls.

        Uses Claude Sonnet 4 pricing:
        - Input tokens: $3.00 per million tokens
        - Output tokens: $15.00 per million tokens
        - Cache creation: $3.75 per million tokens
        - Cache read: $0.30 per million tokens
        """
        async with self.pool.acquire() as conn:
            # Aggregate token usage
            token_result = await conn.fetchrow(
                """
                SELECT
                    SUM((data->>'input_tokens')::int) as total_input,
                    SUM((data->>'output_tokens')::int) as total_output,
                    SUM(COALESCE((data->>'cache_creation_tokens')::int, 0)) as cache_creation,
                    SUM(COALESCE((data->>'cache_read_tokens')::int, 0)) as cache_read
                FROM agent_observations
                WHERE session_id = $1 AND observation_type = 'token_usage'
            """,
                session_id,
            )

            # Count tool calls
            tool_count = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM agent_observations
                WHERE session_id = $1 AND observation_type = 'tool_completed'
            """,
                session_id,
            )

            # Calculate cost (Claude Sonnet 4 pricing)
            # Prices are per million tokens, converted to per-token
            input_cost = Decimal(token_result["total_input"] or 0) * Decimal("0.000003")
            output_cost = Decimal(token_result["total_output"] or 0) * Decimal("0.000015")
            cache_creation_cost = Decimal(token_result["cache_creation"] or 0) * Decimal(
                "0.00000375"
            )
            cache_read_cost = Decimal(token_result["cache_read"] or 0) * Decimal("0.0000003")

            total_cost = input_cost + output_cost + cache_creation_cost + cache_read_cost

            return {
                "session_id": session_id,
                "input_tokens": token_result["total_input"] or 0,
                "output_tokens": token_result["total_output"] or 0,
                "cache_creation_tokens": token_result["cache_creation"] or 0,
                "cache_read_tokens": token_result["cache_read"] or 0,
                "tool_calls": tool_count or 0,
                "total_cost_usd": float(total_cost),
            }

    async def close(self):
        """Close connection pool."""
        if self.pool:
            await self.pool.close()
