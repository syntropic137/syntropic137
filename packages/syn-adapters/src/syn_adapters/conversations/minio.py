"""MinIO implementation of conversation storage.

Stores conversation JSONL files in MinIO/S3 and maintains
an index in PostgreSQL for querying.

See ADR-035: Agent Output Data Model and Storage.
"""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING, Any

import asyncpg

from syn_adapters.conversations.minio_session import (
    create_conversation_storage as _create_conversation_storage,
)
from syn_adapters.conversations.minio_session import get_session_metadata as _get_session_metadata
from syn_adapters.conversations.minio_session import (
    list_sessions_for_execution as _list_sessions_for_execution,
)
from syn_adapters.conversations.minio_session import retrieve_session as _retrieve_session

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

        # Create database pool for metadata queries (session_conversations table).
        # If this fails, MinIO file storage still works but metadata queries
        # will be unavailable. The lifecycle recovery loop will retry (ADR-057).
        try:
            self._pool = await asyncpg.create_pool(self._db_url, min_size=1, max_size=5)
        except Exception:
            self._client = None  # Reset so next initialize() attempt retries fully
            logger.warning(
                "Failed to create database pool for conversation storage "
                "— metadata queries will be unavailable until recovery"
            )
            raise

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

        from syn_adapters.conversations.minio_index import insert_index

        await insert_index(
            self._pool, session_id, object_key, size_bytes, context, self.BUCKET_NAME
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
        return await _retrieve_session(self, session_id)

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
        return await _get_session_metadata(self, session_id)

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
        return await _list_sessions_for_execution(self, execution_id)


# Factory function for easy creation
async def create_conversation_storage(
    endpoint: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    db_url: str | None = None,
) -> MinioConversationStorage:
    """Create and initialize a MinioConversationStorage.

    Uses Pydantic Settings (StorageSettings + Settings) for defaults.

    Args:
        endpoint: MinIO endpoint (default: from settings)
        access_key: Access key (default: from settings)
        secret_key: Secret key (default: from settings)
        db_url: Database URL (default: from settings)

    Returns:
        Initialized MinioConversationStorage
    """
    return await _create_conversation_storage(endpoint, access_key, secret_key, db_url)


# Singleton instance
_conversation_storage_instance: MinioConversationStorage | None = None


def reset_conversation_storage() -> None:
    """Reset the singleton so the next get_conversation_storage() retries initialization.

    Called by the lifecycle recovery loop (ADR-057) after a failed startup.
    """
    global _conversation_storage_instance
    _conversation_storage_instance = None


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
