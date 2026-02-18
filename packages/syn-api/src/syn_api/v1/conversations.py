"""Conversation operations — retrieve session conversation logs from MinIO.

Wraps the ConversationStoragePort for programmatic access.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from syn_api._wiring import ensure_connected, get_conversation_store
from syn_api.types import (
    ConversationLine,
    ConversationLog,
    ConversationMeta,
    Err,
    ObservabilityError,
    Ok,
    Result,
)

if TYPE_CHECKING:
    from syn_api.auth import AuthContext


async def get_conversation_log(
    session_id: str,
    offset: int = 0,
    limit: int = 1000,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[ConversationLog, ObservabilityError]:
    """Retrieve a session's conversation log.

    Args:
        session_id: The session to retrieve.
        offset: Line offset for pagination.
        limit: Maximum lines to return.
        auth: Optional authentication context.

    Returns:
        Ok(ConversationLog) on success, Err(ObservabilityError) on failure.
    """
    await ensure_connected()
    try:
        storage = await get_conversation_store()
        raw_lines = await storage.retrieve_session(session_id)

        if raw_lines is None:
            return Err(
                ObservabilityError.NOT_FOUND,
                message=f"Conversation log not found for session {session_id}",
            )

        total = len(raw_lines)
        page = raw_lines[offset : offset + limit]

        lines = []
        for i, raw in enumerate(page, start=offset + 1):
            event_type = None
            tool_name = None
            preview = None
            try:
                data = json.loads(raw)
                event_type = data.get("type") or data.get("event_type")
                tool_name = data.get("tool_name") or data.get("name")
                content = data.get("content") or data.get("text") or ""
                if isinstance(content, str):
                    preview = content[:200] if content else None
            except (json.JSONDecodeError, AttributeError):
                preview = raw[:200] if raw else None

            lines.append(
                ConversationLine(
                    line_number=i,
                    raw=raw,
                    event_type=event_type,
                    tool_name=tool_name,
                    content_preview=preview,
                )
            )

        return Ok(
            ConversationLog(
                session_id=session_id,
                lines=lines,
                total_lines=total,
            )
        )
    except Exception as e:
        return Err(ObservabilityError.QUERY_FAILED, message=str(e))


async def get_conversation_metadata(
    session_id: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[ConversationMeta | None, ObservabilityError]:
    """Get metadata for a conversation without the full log.

    Args:
        session_id: The session to query.
        auth: Optional authentication context.

    Returns:
        Ok(ConversationMeta) on success, Ok(None) if not found.
    """
    await ensure_connected()
    try:
        storage = await get_conversation_store()
        meta = await storage.get_session_metadata(session_id)

        if meta is None:
            return Ok(None)

        return Ok(
            ConversationMeta(
                session_id=session_id,
                event_count=meta.get("event_count", 0),
                model=meta.get("model"),
                total_input_tokens=meta.get("total_input_tokens", 0),
                total_output_tokens=meta.get("total_output_tokens", 0),
                tool_counts=meta.get("tool_counts", {}),
                started_at=meta.get("started_at"),
                completed_at=meta.get("completed_at"),
            )
        )
    except Exception as e:
        return Err(ObservabilityError.QUERY_FAILED, message=str(e))
