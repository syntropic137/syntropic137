"""MinIO conversation index operations (PostgreSQL-backed).

Extracted from minio.py to reduce module complexity.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncpg

    from syn_adapters.conversations.protocol import SessionContext

logger = logging.getLogger(__name__)


async def insert_index(
    pool: asyncpg.Pool,
    session_id: str,
    object_key: str,
    size_bytes: int,
    context: SessionContext,
    bucket_name: str,
) -> None:
    """Insert or update index entry in database."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO session_conversations (
                session_id, bucket, object_key, size_bytes,
                execution_id, phase_id, workflow_id,
                event_count, total_input_tokens, total_output_tokens, tool_counts,
                started_at, completed_at, model, success
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            ON CONFLICT (session_id) DO UPDATE SET
                object_key = EXCLUDED.object_key,
                size_bytes = EXCLUDED.size_bytes,
                completed_at = EXCLUDED.completed_at,
                event_count = EXCLUDED.event_count,
                total_input_tokens = EXCLUDED.total_input_tokens,
                total_output_tokens = EXCLUDED.total_output_tokens,
                tool_counts = EXCLUDED.tool_counts,
                success = EXCLUDED.success
            """,
            session_id,
            bucket_name,
            object_key,
            size_bytes,
            context.execution_id,
            context.phase_id,
            context.workflow_id,
            context.event_count,
            context.total_input_tokens,
            context.total_output_tokens,
            json.dumps(context.tool_counts) if context.tool_counts else None,
            context.started_at,
            context.completed_at,
            context.model,
            context.success,
        )


async def get_session_metadata(
    pool: asyncpg.Pool,
    session_id: str,
) -> dict[str, Any] | None:
    """Get session metadata from index."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM session_conversations WHERE session_id = $1",
            session_id,
        )
    if row is None:
        return None
    return dict(row)


async def list_sessions_for_execution(
    pool: asyncpg.Pool,
    execution_id: str,
) -> list[str]:
    """Get session IDs for an execution."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT session_id FROM session_conversations
            WHERE execution_id = $1
            ORDER BY started_at
            """,
            execution_id,
        )
    return [row["session_id"] for row in rows]
