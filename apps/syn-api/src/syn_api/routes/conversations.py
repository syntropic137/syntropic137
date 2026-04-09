"""Conversation log API endpoints and service operations.

Provides retrieval of session conversation logs from MinIO storage.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


# =============================================================================
# Response Models
# =============================================================================


class ConversationLineResponse(BaseModel):
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
    lines: list[ConversationLineResponse]
    total_lines: int
    metadata: dict[str, Any] | None = None


class ConversationMetadataResponse(BaseModel):
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


# =============================================================================
# Service functions (importable by tests)
# =============================================================================


def _get_top_level_content(data: dict[str, Any]) -> str:
    """Check top-level ``content`` / ``text`` fields."""
    content = data.get("content") or data.get("text") or ""
    if content and isinstance(content, str):
        return content
    return ""


def _get_message_content(data: dict[str, Any]) -> str:
    """Check nested ``message.content`` (Claude Code JSONL format)."""
    msg = data.get("message")
    if not isinstance(msg, dict):
        return ""
    msg_content = msg.get("content")
    if isinstance(msg_content, str):
        return msg_content
    if isinstance(msg_content, list):
        return next(
            (p["text"] for p in msg_content if isinstance(p, dict) and p.get("text")),
            "",
        )
    return ""


def _get_result_content(data: dict[str, Any]) -> str:
    """Check nested ``result.output`` / ``result.text``."""
    result = data.get("result")
    if isinstance(result, dict):
        return result.get("output", "") or result.get("text", "")
    return ""


def _extract_content_preview(data: dict[str, Any]) -> str:
    """Extract content text from a parsed JSONL object.

    Checks top-level fields, then nested message.content (Claude Code format),
    then result.output.
    """
    return _get_top_level_content(data) or _get_message_content(data) or _get_result_content(data)


def _extract_line_fields(
    raw: str,
) -> tuple[str | None, str | None, str | None]:
    """Extract event_type, tool_name, and content preview from a JSONL line.

    Returns (event_type, tool_name, preview) — all None-able.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, AttributeError):
        preview = raw[:200] if raw else None
        return None, None, preview

    event_type = data.get("type") or data.get("event_type")
    tool_name = data.get("tool_name") or data.get("name")
    content = _extract_content_preview(data)
    preview = content[:200] if content else None
    return event_type, tool_name, preview


def _parse_conversation_line(line_number: int, raw: str) -> ConversationLine:
    """Parse a single raw JSONL line into a ConversationLine."""
    event_type, tool_name, preview = _extract_line_fields(raw)
    return ConversationLine(
        line_number=line_number,
        raw=raw,
        event_type=event_type,
        tool_name=tool_name,
        content_preview=preview,
    )


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
        lines = [_parse_conversation_line(i, raw) for i, raw in enumerate(page, start=offset + 1)]

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
                tool_counts=meta.get("tool_counts") or {},
                started_at=meta.get("started_at"),
                completed_at=meta.get("completed_at"),
                size_bytes=meta.get("size_bytes"),
                execution_id=meta.get("execution_id"),
                workflow_id=meta.get("workflow_id"),
                phase_id=meta.get("phase_id"),
                success=meta.get("success"),
            )
        )
    except Exception as e:
        return Err(ObservabilityError.QUERY_FAILED, message=str(e))


# =============================================================================
# HTTP Endpoints
# =============================================================================


@router.get("/{session_id}", response_model=ConversationLogResponse)
async def get_conversation_log_endpoint(
    session_id: str,
    offset: int = 0,
    limit: int = 100,
) -> ConversationLogResponse:
    """Get conversation log for a session."""
    from syn_api._wiring import get_projection_mgr
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    session_id = await resolve_or_raise(mgr.store, "session_summaries", session_id, "Session")
    if limit > 500:
        limit = 500

    result = await get_conversation_log(
        session_id=session_id,
        offset=offset,
        limit=limit,
    )

    if isinstance(result, Err):
        if "not found" in (result.message or "").lower():
            raise HTTPException(
                status_code=404,
                detail=f"Conversation log not found for session: {session_id}",
            )
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving conversation log: {result.message}",
        )

    log = result.value
    return ConversationLogResponse(
        session_id=log.session_id,
        lines=[
            ConversationLineResponse(
                line_number=line.line_number,
                raw=line.raw,
                event_type=line.event_type,
                tool_name=line.tool_name,
                content_preview=line.content_preview,
            )
            for line in log.lines
        ],
        total_lines=log.total_lines,
        metadata=log.metadata,
    )


@router.get("/{session_id}/metadata", response_model=ConversationMetadataResponse)
async def get_conversation_metadata_endpoint(
    session_id: str,
) -> ConversationMetadataResponse:
    """Get conversation metadata for a session."""
    from syn_api._wiring import get_projection_mgr
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    session_id = await resolve_or_raise(mgr.store, "session_summaries", session_id, "Session")
    result = await get_conversation_metadata(session_id)

    if isinstance(result, Err):
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving conversation metadata: {result.message}",
        )

    meta = result.value
    if meta is None:
        raise HTTPException(
            status_code=404,
            detail=f"No metadata found for session: {session_id}",
        )

    return ConversationMetadataResponse(
        session_id=session_id,
        event_count=meta.event_count,
        total_input_tokens=meta.total_input_tokens,
        total_output_tokens=meta.total_output_tokens,
        tool_counts=meta.tool_counts,
        started_at=str(meta.started_at) if meta.started_at else None,
        completed_at=str(meta.completed_at) if meta.completed_at else None,
        model=meta.model,
        size_bytes=meta.size_bytes,
        execution_id=meta.execution_id,
        workflow_id=meta.workflow_id,
        phase_id=meta.phase_id,
        success=meta.success,
    )
