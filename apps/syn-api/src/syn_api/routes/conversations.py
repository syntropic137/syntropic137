"""Conversation log API endpoints and service operations.

Provides retrieval of session conversation logs from MinIO storage.
"""

from __future__ import annotations

import json
import logging
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Mapping

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
from syn_shared.codex_stream import (
    CODEX_TOOL_NAME_COMMAND,
    CODEX_TOOL_NAME_FILE_CHANGE,
    CodexItemType,
    CodexStreamType,
)

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


class TranscriptEventType(StrEnum):
    """Normalized display event-type a transcript line renders as.

    Claude's ``stream-json`` already emits ``assistant`` / ``user`` / ``result``
    / ``system`` as its top-level ``type``; the codex path is normalized ONTO
    the same vocabulary so the dashboard's single color map styles both. These
    strings are mirrored by ``conversationEventColors`` in the frontend
    (``sessionConstants.ts``) - keep them in sync.
    """

    ASSISTANT = "assistant"
    TOOL_USE = "tool_use"
    SYSTEM = "system"
    RESULT = "result"
    ERROR = "error"
    LOG = "log"
    """A non-JSON CLI diagnostic line (codex writes these to stdout)."""


_PREVIEW_LEN = 200

# Codex writes plain-text banners to stdout alongside its JSONL events. These
# are pure CLI chrome (not conversation, not diagnostics) and are dropped from
# the transcript entirely. Matched by prefix on non-JSON lines only.
# Source: CodexStreamProcessor golden-fixture note (2026-07-23).
_CODEX_CLI_NOISE_PREFIXES = (
    "Reading additional input from stdin",
    "warning: --full-auto is deprecated",
)

_CODEX_STREAM_TYPES = frozenset(t.value for t in CodexStreamType)


def _log_line_preview(raw: str) -> str | None:
    """Preview for a non-object transcript line (CLI diagnostic or JSON scalar)."""
    stripped = raw.strip() if raw else ""
    return stripped[:_PREVIEW_LEN] if stripped else None


def _is_codex_cli_noise(raw: str) -> bool:
    """True for a codex plain-text banner line that should not appear at all."""
    stripped = raw.strip()
    if not stripped or stripped.startswith("{"):
        return False
    return any(stripped.startswith(prefix) for prefix in _CODEX_CLI_NOISE_PREFIXES)


def _codex_file_change_preview(item: Mapping[str, object]) -> str | None:
    """Join the changed paths in a codex ``file_change`` item into a preview."""
    changes = item.get("changes")
    if not isinstance(changes, list):
        return None
    paths = [str(c.get("path", "")) for c in changes if isinstance(c, dict) and c.get("path")]
    joined = ", ".join(paths)
    return joined[:_PREVIEW_LEN] if joined else None


def _codex_command_execution_preview(
    item: Mapping[str, object], stream_type: CodexStreamType
) -> str | None:
    """Preview for a codex ``command_execution`` item.

    Codex emits both ``item.started`` and ``item.completed`` for the same
    command. ``item.started`` carries the invocation (the ``command``);
    ``item.completed`` carries the result (``aggregated_output``). Without
    this split, both rows show the same command string, so the same tool
    call renders twice in the transcript with no new information on the
    second line. Falls back to the command when the output is empty (e.g.
    a command that produced no stdout).
    """
    command = item.get("command")
    command_preview = command[:_PREVIEW_LEN] if isinstance(command, str) and command else None
    if stream_type == CodexStreamType.ITEM_COMPLETED:
        output = item.get("aggregated_output")
        if isinstance(output, str) and output:
            return output[:_PREVIEW_LEN]
    return command_preview


def _codex_item_fields(
    item: Mapping[str, object], stream_type: CodexStreamType
) -> tuple[str, str | None, str | None]:
    """Map a codex stream ``item`` to (event_type, tool_name, preview)."""
    item_type = item.get("type")
    if item_type == CodexItemType.AGENT_MESSAGE:
        text = item.get("text")
        preview = text[:_PREVIEW_LEN] if isinstance(text, str) and text else None
        return TranscriptEventType.ASSISTANT, None, preview
    if item_type == CodexItemType.COMMAND_EXECUTION:
        preview = _codex_command_execution_preview(item, stream_type)
        return TranscriptEventType.TOOL_USE, CODEX_TOOL_NAME_COMMAND, preview
    if item_type == CodexItemType.FILE_CHANGE:
        return (
            TranscriptEventType.TOOL_USE,
            CODEX_TOOL_NAME_FILE_CHANGE,
            _codex_file_change_preview(item),
        )
    return TranscriptEventType.SYSTEM, None, None


def _extract_codex_fields(
    data: Mapping[str, object],
) -> tuple[str, str | None, str | None] | None:
    """Normalize a codex stream event, or None if the line is not codex-shaped.

    Codex's ``--json`` events use a closed set of top-level ``type`` values
    (``item.completed`` etc.) unrelated to claude's ``stream-json`` types, so a
    ``type`` in that set unambiguously identifies a codex line. Returning None
    lets the caller fall back to claude parsing.
    """
    raw_type = data.get("type")
    if raw_type not in _CODEX_STREAM_TYPES:
        return None
    if raw_type == CodexStreamType.TURN_COMPLETED:
        return TranscriptEventType.RESULT, None, None
    if raw_type == CodexStreamType.TURN_FAILED:
        error = data.get("error")
        preview = str(error)[:_PREVIEW_LEN] if error else None
        return TranscriptEventType.ERROR, None, preview
    item = data.get("item")
    if not isinstance(item, dict):
        return TranscriptEventType.SYSTEM, None, None
    return _codex_item_fields(item, CodexStreamType(raw_type))


def _extract_line_fields(
    raw: str,
) -> tuple[str | None, str | None, str | None]:
    """Extract event_type, tool_name, and content preview from a JSONL line.

    Handles both claude ``stream-json`` and codex ``--json`` line shapes.
    Returns (event_type, tool_name, preview) — all None-able.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, AttributeError):
        # Non-JSON line: a codex CLI diagnostic (e.g. an ERROR trace) on stdout.
        # Label it ``log`` rather than leaving it to render as "unknown".
        return TranscriptEventType.LOG, None, _log_line_preview(raw)

    # Valid JSON but not an object (a bare scalar/array). Both the codex and
    # claude extractors call ``.get()``, so guard here - otherwise one odd line
    # (``null``, ``[]``, ``"diagnostic"``) would raise and fail the WHOLE
    # transcript request with QUERY_FAILED.
    if not isinstance(data, dict):
        return TranscriptEventType.LOG, None, _log_line_preview(raw)

    codex = _extract_codex_fields(data)
    if codex is not None:
        return codex

    event_type = data.get("type") or data.get("event_type")
    tool_name = data.get("tool_name") or data.get("name")
    content = _extract_content_preview(data)
    preview = content[:_PREVIEW_LEN] if content else None
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
) -> Result[ConversationLog, ObservabilityError]:
    """Retrieve a session's conversation log.

    Args:
        session_id: The session to retrieve.
        offset: Line offset for pagination.
        limit: Maximum lines to return.

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

        # Drop codex CLI banner noise before numbering so line numbers and
        # total_lines reflect only real transcript content.
        raw_lines = [line for line in raw_lines if not _is_codex_cli_noise(line)]

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
) -> Result[ConversationMeta | None, ObservabilityError]:
    """Get metadata for a conversation without the full log.

    Args:
        session_id: The session to query.

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
