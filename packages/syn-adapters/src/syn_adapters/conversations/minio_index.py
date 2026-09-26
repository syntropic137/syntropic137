"""MinIO conversation index operations (PostgreSQL-backed).

Extracted from minio.py to reduce module complexity.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

from syn_adapters.postgres_text import pg_json, pg_safe
from syn_shared.observed_model import (
    OBSERVED_MODEL_KEY,
    REQUESTED_MODEL_KEY,
    RecordedModel,
    split_recorded_model,
)

if TYPE_CHECKING:
    import asyncpg

    from syn_adapters.conversations.protocol import SessionContext

logger = logging.getLogger(__name__)


# insert_index normalises the ids it stores, so the two readers below normalise
# the ids they ask for. Sanitising only the write side files the row under a name
# no caller can name, which loses the conversation rather than failing (#1241).


#: The column ADR-067 added. Named once so the DDL, the probe and the insert
#: cannot disagree about it.
REQUESTED_MODEL_COLUMN: Final[str] = REQUESTED_MODEL_KEY

#: Hand-applied spelling: projection_stores/migrations/006_session_conversations_requested_model.sql.
ADD_REQUESTED_MODEL_COLUMN_SQL: Final[str] = (
    f"ALTER TABLE session_conversations ADD COLUMN IF NOT EXISTS {REQUESTED_MODEL_COLUMN} TEXT"
)

_HAS_REQUESTED_MODEL_COLUMN_SQL: Final[str] = f"""
SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'session_conversations' AND column_name = '{REQUESTED_MODEL_COLUMN}'
)
"""

_INSERT_COLUMNS: Final[str] = """
                session_id, bucket, object_key, size_bytes,
                execution_id, phase_id, workflow_id,
                event_count, total_input_tokens, total_output_tokens, tool_counts,
                started_at, completed_at, model, success"""

_ON_CONFLICT: Final[str] = """
            ON CONFLICT (session_id) DO UPDATE SET
                object_key = EXCLUDED.object_key,
                size_bytes = EXCLUDED.size_bytes,
                completed_at = EXCLUDED.completed_at,
                event_count = EXCLUDED.event_count,
                total_input_tokens = EXCLUDED.total_input_tokens,
                total_output_tokens = EXCLUDED.total_output_tokens,
                tool_counts = EXCLUDED.tool_counts,
                model = EXCLUDED.model,
                success = EXCLUDED.success"""

_INSERT_SQL: Final[str] = f"""
            INSERT INTO session_conversations ({_INSERT_COLUMNS}
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            {_ON_CONFLICT}
"""

_INSERT_WITH_REQUESTED_MODEL_SQL: Final[str] = f"""
            INSERT INTO session_conversations ({_INSERT_COLUMNS}, {REQUESTED_MODEL_COLUMN}
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            {_ON_CONFLICT},
                {REQUESTED_MODEL_COLUMN} = EXCLUDED.{REQUESTED_MODEL_COLUMN}
"""


async def ensure_requested_model_column(pool: asyncpg.Pool, *, auto_create: bool) -> bool:
    """Whether the index can store ``requested_model``, adding the column if allowed.

    A deployment created before ADR-067 has no such column. When the process
    may alter the schema (``SYN_SKIP_AUTO_CREATE_TABLES`` unset) it is added
    here, idempotently; otherwise the migration is the operator's and this
    only reports whether it has been applied. Either way the answer decides
    which INSERT runs, so a missing column costs the requested model, never
    the transcript's index row.
    """
    async with pool.acquire() as conn:
        if auto_create:
            try:
                await conn.execute(ADD_REQUESTED_MODEL_COLUMN_SQL)
            except Exception:
                logger.warning(
                    "Could not add session_conversations.%s - conversations will be "
                    "indexed without the requested model",
                    REQUESTED_MODEL_COLUMN,
                    exc_info=True,
                )
        return bool(await conn.fetchval(_HAS_REQUESTED_MODEL_COLUMN_SQL))


async def insert_index(
    pool: asyncpg.Pool,
    session_id: str,
    object_key: str,
    size_bytes: int,
    context: SessionContext,
    bucket_name: str,
    *,
    with_requested_model: bool = False,
) -> None:
    """Insert or update index entry in database.

    ``model`` is refreshed on conflict as well: a re-stored session may now
    know the model its harness reported, and the stale value is the one that
    would otherwise stick (ADR-067).
    """
    extra: tuple[str | None, ...] = (
        (pg_safe(context.requested_model),) if with_requested_model else ()
    )
    async with pool.acquire() as conn:
        await conn.execute(
            _INSERT_WITH_REQUESTED_MODEL_SQL if with_requested_model else _INSERT_SQL,
            pg_safe(session_id),
            bucket_name,
            pg_safe(object_key),
            size_bytes,
            pg_safe(context.execution_id),
            pg_safe(context.phase_id),
            pg_safe(context.workflow_id),
            context.event_count,
            context.total_input_tokens,
            context.total_output_tokens,
            pg_json(context.tool_counts) if context.tool_counts else None,
            context.started_at,
            context.completed_at,
            pg_safe(context.model),
            context.success,
            *extra,
        )


async def get_session_metadata(
    pool: asyncpg.Pool,
    session_id: str,
) -> dict[str, Any] | None:
    """Get session metadata from index."""
    session_id = pg_safe(session_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM session_conversations WHERE session_id = $1",
            session_id,
        )
    if row is None:
        return None
    metadata = dict(row)
    # Reported as observed and requested (ADR-067), whichever era wrote it.
    recorded = index_row_model(
        metadata.get(OBSERVED_MODEL_KEY), metadata.get(REQUESTED_MODEL_COLUMN)
    )
    metadata[OBSERVED_MODEL_KEY] = recorded.observed
    metadata[REQUESTED_MODEL_COLUMN] = recorded.requested
    return metadata


def index_row_model(model: object, requested_model: object) -> RecordedModel:
    """Classify an index row's ``model`` / ``requested_model`` columns (ADR-067).

    Rows indexed before ADR-067 filed the phase's REQUESTED model - often an
    alias - under ``model``. They are classified with ``split_recorded_model``
    so an alias is reported as the request it was, never as the model that ran.

    A SQL NULL cannot say whether a key was written, so a row is treated as
    carrying the key only when ``requested_model`` is non-null. For a row that
    genuinely requested nothing that loses nothing: its ``model`` is an id or
    null, which both readings keep as written.
    """
    return split_recorded_model(
        model,
        requested_model,
        has_requested_key=requested_model is not None,
    )


async def list_sessions_for_execution(
    pool: asyncpg.Pool,
    execution_id: str,
) -> list[str]:
    """Get session IDs for an execution."""
    execution_id = pg_safe(execution_id)
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
