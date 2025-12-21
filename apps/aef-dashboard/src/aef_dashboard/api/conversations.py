"""Conversation log API endpoints.

Provides access to full conversation logs stored in MinIO/S3.
See ADR-035: Agent Output Data Model and Storage.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationLine(BaseModel):
    """A single line from the conversation log."""

    line_number: int
    raw: str
    parsed: dict[str, Any] | None = None
    event_type: str | None = None
    tool_name: str | None = None
    content_preview: str | None = None


class ConversationLogResponse(BaseModel):
    """Response containing conversation log."""

    session_id: str
    lines: list[ConversationLine]
    total_lines: int
    metadata: dict[str, Any] | None = None


class ConversationMetadata(BaseModel):
    """Conversation index metadata."""

    session_id: str
    execution_id: str | None = None
    workflow_id: str | None = None
    phase_id: str | None = None
    event_count: int | None = None
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    tool_counts: dict[str, int] | None = None
    started_at: str | None = None
    completed_at: str | None = None
    model: str | None = None
    success: bool | None = None
    size_bytes: int | None = None


def _parse_conversation_line(line: str, line_number: int) -> ConversationLine:
    """Parse a JSONL line and extract summary info."""
    parsed: dict[str, Any] | None = None
    event_type: str | None = None
    tool_name: str | None = None
    content_preview: str | None = None

    try:
        parsed = json.loads(line)
        event_type = parsed.get("type")

        # Extract tool name from tool_use events
        if event_type == "assistant":
            message = parsed.get("message", {})
            content = message.get("content", [])
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "tool_use":
                        tool_name = item.get("name")
                        break
                    if item.get("type") == "text":
                        text = item.get("text", "")
                        content_preview = text[:200] if len(text) > 200 else text
                        break

        # Extract content preview from system messages
        if event_type == "system":
            subtype = parsed.get("subtype")
            if subtype:
                content_preview = f"[{subtype}]"

        # Extract result info
        if event_type == "result":
            is_error = parsed.get("is_error", False)
            content_preview = "Error" if is_error else "Success"

    except json.JSONDecodeError:
        pass

    return ConversationLine(
        line_number=line_number,
        raw=line,
        parsed=parsed,
        event_type=event_type,
        tool_name=tool_name,
        content_preview=content_preview,
    )


async def _get_conversation_storage():
    """Get or create conversation storage instance."""
    from aef_adapters.conversations import MinioConversationStorage

    storage = MinioConversationStorage(
        endpoint=os.environ.get("AEF_STORAGE_MINIO_ENDPOINT", "localhost:9000"),
        access_key=os.environ.get("AEF_STORAGE_MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.environ.get("AEF_STORAGE_MINIO_SECRET_KEY", "minioadmin"),
        db_url=os.environ.get(
            "AEF_DATABASE_URL", "postgresql://aef:aef_dev_password@localhost:5432/aef"
        ),
    )
    await storage.initialize()
    return storage


@router.get("/{session_id}", response_model=ConversationLogResponse)
async def get_conversation_log(
    session_id: str,
    offset: int = 0,
    limit: int = 100,
) -> ConversationLogResponse:
    """Get conversation log for a session.

    Args:
        session_id: The session ID
        offset: Starting line number (0-indexed)
        limit: Max lines to return (default 100, max 500)

    Returns:
        Parsed conversation log with line-by-line content
    """
    if limit > 500:
        limit = 500

    try:
        storage = await _get_conversation_storage()

        # Get the raw lines
        lines = await storage.retrieve_session(session_id)
        if lines is None:
            raise HTTPException(
                status_code=404,
                detail=f"Conversation log not found for session: {session_id}",
            )

        # Get metadata
        metadata = await storage.get_session_metadata(session_id)

        # Apply pagination
        total_lines = len(lines)
        paginated_lines = lines[offset : offset + limit]

        # Parse each line
        parsed_lines = [
            _parse_conversation_line(line, offset + i) for i, line in enumerate(paginated_lines)
        ]

        await storage.close()

        return ConversationLogResponse(
            session_id=session_id,
            lines=parsed_lines,
            total_lines=total_lines,
            metadata=metadata,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error retrieving conversation log: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving conversation log: {e}",
        ) from e


@router.get("/{session_id}/metadata", response_model=ConversationMetadata | None)
async def get_conversation_metadata(session_id: str) -> ConversationMetadata | None:
    """Get conversation metadata for a session.

    This returns the indexed metadata without fetching the full log.
    """
    try:
        storage = await _get_conversation_storage()
        metadata = await storage.get_session_metadata(session_id)
        await storage.close()

        if metadata is None:
            return None

        return ConversationMetadata(
            session_id=metadata.get("session_id", session_id),
            execution_id=metadata.get("execution_id"),
            workflow_id=metadata.get("workflow_id"),
            phase_id=metadata.get("phase_id"),
            event_count=metadata.get("event_count"),
            total_input_tokens=metadata.get("total_input_tokens"),
            total_output_tokens=metadata.get("total_output_tokens"),
            tool_counts=metadata.get("tool_counts"),
            started_at=str(metadata["started_at"]) if metadata.get("started_at") else None,
            completed_at=str(metadata["completed_at"]) if metadata.get("completed_at") else None,
            model=metadata.get("model"),
            success=metadata.get("success"),
            size_bytes=metadata.get("size_bytes"),
        )

    except Exception as e:
        logger.exception("Error retrieving conversation metadata: %s", e)
        return None
