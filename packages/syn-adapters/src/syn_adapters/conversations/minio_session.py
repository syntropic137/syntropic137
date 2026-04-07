"""MinIO conversation session retrieval and factory helpers.

Extracted from minio.py to reduce module complexity.
Handles session retrieval, metadata lookup, execution listing, and storage factory.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syn_adapters.conversations.minio import MinioConversationStorage

logger = logging.getLogger(__name__)


async def retrieve_session(
    storage: MinioConversationStorage,
    session_id: str,
) -> list[str] | None:
    """Retrieve a session's conversation log.

    Args:
        storage: MinioConversationStorage instance.
        session_id: Session identifier

    Returns:
        List of JSONL lines, or None if not found
    """
    if not storage._initialized:
        await storage.initialize()

    object_key = f"sessions/{session_id}/conversation.jsonl"

    try:
        assert storage._client is not None, "Storage not initialized"
        response = storage._client.get_object(storage.BUCKET_NAME, object_key)
        content = response.read().decode("utf-8")
        response.close()
        response.release_conn()
        return content.strip().split("\n")
    except Exception as e:
        logger.debug("Session not found: %s (%s)", session_id, e)
        return None


async def get_session_metadata(
    storage: MinioConversationStorage,
    session_id: str,
) -> dict[str, Any] | None:
    """Get session metadata from index.

    Args:
        storage: MinioConversationStorage instance.
        session_id: Session identifier

    Returns:
        Session metadata dict, or None if not found
    """
    if not storage._initialized:
        await storage.initialize()

    if storage._pool is None:
        logger.warning(
            "Conversation storage database pool not available "
            "— cannot query metadata for session %s",
            session_id,
        )
        return None

    from syn_adapters.conversations.minio_index import get_session_metadata as _get_metadata

    return await _get_metadata(storage._pool, session_id)


async def list_sessions_for_execution(
    storage: MinioConversationStorage,
    execution_id: str,
) -> list[str]:
    """Get session IDs for an execution.

    Args:
        storage: MinioConversationStorage instance.
        execution_id: Execution identifier

    Returns:
        List of session IDs
    """
    if not storage._initialized:
        await storage.initialize()

    if storage._pool is None:
        logger.warning(
            "Conversation storage database pool not available "
            "— cannot list sessions for execution %s",
            execution_id,
        )
        return []

    from syn_adapters.conversations.minio_index import (
        list_sessions_for_execution as _list_sessions,
    )

    return await _list_sessions(storage._pool, execution_id)


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
    from syn_adapters.conversations.minio import MinioConversationStorage
    from syn_shared.settings import get_settings

    settings = get_settings()
    storage_settings = settings.storage

    storage = MinioConversationStorage(
        endpoint=endpoint or storage_settings.minio_endpoint or "localhost:9000",
        access_key=access_key or storage_settings.minio_access_key or "minioadmin",
        secret_key=secret_key
        or storage_settings.minio_secret_key.get_secret_value()
        or "minioadmin",
        db_url=db_url
        or str(
            settings.syn_observability_db_url
            or "postgresql://syn:syn_dev_password@localhost:5432/syn"
        ),
        secure=storage_settings.minio_secure,
    )
    await storage.initialize()
    return storage
