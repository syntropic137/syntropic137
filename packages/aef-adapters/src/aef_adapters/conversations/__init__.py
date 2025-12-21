"""Conversation storage adapters.

Provides storage for full conversation logs (JSONL) in S3-compatible storage.
See ADR-035: Agent Output Data Model and Storage.

Usage:
    from aef_adapters.conversations import (
        ConversationStoragePort,
        MinioConversationStorage,
        SessionContext,
    )

    storage = MinioConversationStorage(
        endpoint="localhost:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
    )

    await storage.store_session(
        session_id="session-123",
        lines=["line1", "line2"],
        context=SessionContext(...),
    )
"""

from aef_adapters.conversations.minio import (
    MinioConversationStorage,
    get_conversation_storage,
)
from aef_adapters.conversations.protocol import (
    ConversationStoragePort,
    SessionContext,
)

__all__ = [
    "ConversationStoragePort",
    "MinioConversationStorage",
    "SessionContext",
    "get_conversation_storage",
]
