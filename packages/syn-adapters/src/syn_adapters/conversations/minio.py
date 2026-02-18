"""MinIO implementation of conversation storage.

Stores conversation JSONL files in MinIO/S3 and maintains
an index in PostgreSQL for querying.

See ADR-035: Agent Output Data Model and Storage.
"""

from __future__ import annotations

import io
import json
import logging
from typing import TYPE_CHECKING, Any

import asyncpg

if TYPE_CHECKING:
    from syn_adapters.conversations.protocol import SessionContext

logger = logging.getLogger(__name__)


class MinioConversationStorage:
    """MinIO-based conversation storage.

    Stores full JSONL conversation logs in MinIO and maintains
    an index in the session_conversations table.

    Usage:
        storage = MinioConversationStorage(
            endpoint="localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            db_url="postgresql://syn:syn@localhost:5432/syn",
        )
        await storage.initialize()

        await storage.store_session(
            session_id="session-123",
            lines=conversation_buffer,
            context=SessionContext(
                execution_id="exec-456",
                phase_id="phase-1",
                ...
            ),
        )
    """

    BUCKET_NAME = "syn-conversations"

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        db_url: str,
        secure: bool = False,
    ) -> None:
        """Initialize the storage.

        Args:
            endpoint: MinIO endpoint (host:port)
            access_key: MinIO access key
            secret_key: MinIO secret key
            db_url: PostgreSQL connection URL
            secure: Whether to use HTTPS
        """
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._db_url = db_url
        self._secure = secure

        self._client: Any = None
        self._pool: asyncpg.Pool | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize MinIO client and database pool."""
        if self._initialized:
            return

        # Import minio here to avoid import errors if not installed
        from minio import Minio

        # Create MinIO client
        self._client = Minio(
            self._endpoint,
            access_key=self._access_key,
            secret_key=self._secret_key,
            secure=self._secure,
        )

        # Ensure bucket exists
        if not self._client.bucket_exists(self.BUCKET_NAME):
            self._client.make_bucket(self.BUCKET_NAME)
            logger.info("Created bucket: %s", self.BUCKET_NAME)

        # Create database pool
        self._pool = await asyncpg.create_pool(self._db_url, min_size=1, max_size=5)

        self._initialized = True
        logger.info("MinioConversationStorage initialized")

    async def close(self) -> None:
        """Close resources."""
        if self._pool:
            await self._pool.close()

    async def store_session(
        self,
        session_id: str,
        lines: list[str],
        context: SessionContext,
    ) -> str:
        """Store a session's conversation log.

        Args:
            session_id: Unique session identifier
            lines: List of JSONL lines
            context: Session context for indexing

        Returns:
            Object key where conversation was stored
        """
        if not self._initialized:
            await self.initialize()

        # Build object key
        object_key = f"sessions/{session_id}/conversation.jsonl"

        # Join lines into JSONL content
        content = "\n".join(lines)
        content_bytes = content.encode("utf-8")
        size_bytes = len(content_bytes)

        # Upload to MinIO
        self._client.put_object(
            self.BUCKET_NAME,
            object_key,
            io.BytesIO(content_bytes),
            length=size_bytes,
            content_type="application/jsonl",
        )
        logger.info("Stored conversation: %s (%d bytes)", object_key, size_bytes)

        # Insert index entry
        await self._insert_index(session_id, object_key, size_bytes, context)

        return object_key

    async def _insert_index(
        self,
        session_id: str,
        object_key: str,
        size_bytes: int,
        context: SessionContext,
    ) -> None:
        """Insert or update index entry in database."""
        if self._pool is None:
            raise RuntimeError("Storage not initialized")

        async with self._pool.acquire() as conn:
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
                self.BUCKET_NAME,
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

    async def retrieve_session(
        self,
        session_id: str,
    ) -> list[str] | None:
        """Retrieve a session's conversation log.

        Args:
            session_id: Session identifier

        Returns:
            List of JSONL lines, or None if not found
        """
        if not self._initialized:
            await self.initialize()

        object_key = f"sessions/{session_id}/conversation.jsonl"

        try:
            response = self._client.get_object(self.BUCKET_NAME, object_key)
            content = response.read().decode("utf-8")
            response.close()
            response.release_conn()
            return content.strip().split("\n")
        except Exception as e:
            logger.debug("Session not found: %s (%s)", session_id, e)
            return None

    async def get_session_metadata(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Get session metadata from index.

        Args:
            session_id: Session identifier

        Returns:
            Session metadata dict, or None if not found
        """
        if not self._initialized:
            await self.initialize()

        if self._pool is None:
            return None

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM session_conversations WHERE session_id = $1
                """,
                session_id,
            )

        if row is None:
            return None

        return dict(row)

    async def list_sessions_for_execution(
        self,
        execution_id: str,
    ) -> list[str]:
        """Get session IDs for an execution.

        Args:
            execution_id: Execution identifier

        Returns:
            List of session IDs
        """
        if not self._initialized:
            await self.initialize()

        if self._pool is None:
            return []

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id FROM session_conversations
                WHERE execution_id = $1
                ORDER BY started_at
                """,
                execution_id,
            )

        return [row["session_id"] for row in rows]


# Factory function for easy creation
async def create_conversation_storage(
    endpoint: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    db_url: str | None = None,
) -> MinioConversationStorage:
    """Create and initialize a MinioConversationStorage.

    Uses environment variables if parameters not provided:
    - SYN_STORAGE_MINIO_ENDPOINT
    - SYN_STORAGE_MINIO_ACCESS_KEY
    - SYN_STORAGE_MINIO_SECRET_KEY
    - SYN_DATABASE_URL

    Args:
        endpoint: MinIO endpoint (default: from env)
        access_key: Access key (default: from env)
        secret_key: Secret key (default: from env)
        db_url: Database URL (default: from env)

    Returns:
        Initialized MinioConversationStorage
    """
    import os

    storage = MinioConversationStorage(
        endpoint=endpoint or os.environ.get("SYN_STORAGE_MINIO_ENDPOINT", "localhost:9000"),
        access_key=access_key or os.environ.get("SYN_STORAGE_MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=secret_key or os.environ.get("SYN_STORAGE_MINIO_SECRET_KEY", "minioadmin"),
        db_url=db_url
        or os.environ.get(
            "SYN_OBSERVABILITY_DB_URL", "postgresql://syn:syn_dev_password@localhost:5432/syn"
        ),
    )
    await storage.initialize()
    return storage


# Singleton instance
_conversation_storage_instance: MinioConversationStorage | None = None


async def get_conversation_storage() -> MinioConversationStorage:
    """Get the singleton conversation storage instance.

    Creates and initializes the storage on first call.
    Subsequent calls return the same instance.

    Returns:
        Initialized MinioConversationStorage instance
    """
    global _conversation_storage_instance
    if _conversation_storage_instance is None:
        _conversation_storage_instance = await create_conversation_storage()
    return _conversation_storage_instance
