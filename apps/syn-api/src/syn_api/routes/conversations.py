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


def _codex_command_execution_preview(item: Mapping[str, object]) -> str | None:
    """Preview for a completed codex ``command_execution`` item.

    Prefers the result (``aggregated_output``); falls back to the invocation
    (``command``) when the output is empty (e.g. a command that produced no
    stdout), so the row is never blank.
    """
    output = item.get("aggregated_output")
    if isinstance(output, str) and output:
        return output[:_PREVIEW_LEN]
    command = item.get("command")
    return command[:_PREVIEW_LEN] if isinstance(command, str) and command else None


# Claude Code's stream-json nests a tool call inside
# ``message.content[].{type: "tool_use", name, input}`` (assistant lines) and
# the matching result inside
# ``message.content[].{type: "tool_result", content, is_error}`` (user
# lines). There is no top-level ``tool_name``/``name`` key for either, so the
# generic extractor below always falls through to None for these - this is
# the claude-side counterpart to ``_extract_codex_fields``.
_TOOL_PREVIEW_LEN = 100

# Priority order of input keys to surface as a tool_use preview, checked by
# field name rather than dispatching on tool name so new/renamed tools still
# get a preview: ``command`` for Bash, ``file_path`` for Read/Edit/Write,
# ``pattern`` for Grep/Glob, etc.
_CLAUDE_TOOL_INPUT_KEYS = (
    "command",
    "file_path",
    "pattern",
    "path",
    "notebook_path",
    "url",
    "query",
    "description",
    "prompt",
)


def _claude_tool_use_preview(input_data: Mapping[str, object]) -> str | None:
    """Pick the first populated salient field from a ``tool_use`` block's input."""
    for key in _CLAUDE_TOOL_INPUT_KEYS:
        value = input_data.get(key)
        if isinstance(value, str) and value:
            return value[:_TOOL_PREVIEW_LEN]
    return None


def _claude_tool_result_text(content: object) -> str:
    """Flatten a ``tool_result`` block's ``content`` into plain text.

    ``content`` is either a bare string, or a list of ``{"type": "text",
    "text": ...}`` blocks (seen in real recordings, e.g. subagent tool
    results) - join those in order.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part["text"]
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def _claude_tool_result_preview(item: Mapping[str, object]) -> str | None:
    """Preview for a ``tool_result`` block: its first output line, error-flagged."""
    text = _claude_tool_result_text(item.get("content"))
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    if item.get("is_error") is True:
        return f"[error] {first_line}"[:_TOOL_PREVIEW_LEN] if first_line else "[error]"
    return first_line[:_TOOL_PREVIEW_LEN] if first_line else None


# ``message.content[]`` is a LIST, and every tool block in it is a distinct
# call or result. One raw line therefore maps to N tool blocks but only ONE
# ``ConversationLine``, whose ``tool_name``/``content_preview`` are each a
# single ``str | None`` - so the blocks are joined rather than dropped.
#
# Separator is " | " and not ", " (the separator ``_codex_file_change_preview``
# uses for paths) because these values are commands and command output, in
# which commas are ordinary content; a comma would be indistinguishable from
# the preview text itself, while " | " keeps the block boundaries readable.
_TOOL_FIELD_SEP = " | "


def _extract_claude_tool_fields(
    data: Mapping[str, object],
) -> tuple[str, str | None, str | None] | None:
    """Normalize a claude ``tool_use``/``tool_result`` line, or None otherwise.

    Only ``assistant`` and ``user`` lines whose ``message.content[]`` contains
    a ``tool_use`` or ``tool_result`` block are handled here; every other
    shape (plain assistant text, a plain user turn, system/init, result,
    an unrecognized type) returns None so the caller falls back to the
    generic extractor, which already handles those correctly.

    EVERY tool block on the line is represented, not just the first. An
    assistant message that makes parallel tool calls carries one ``tool_use``
    block per call, and the matching ``user`` message carries one
    ``tool_result`` block per call; ``agentic_isolation``'s claude_cli
    ``event_parser`` - the harness-side authority on this format - likewise
    emits one observability event per block rather than stopping at the first.
    Returning on the first block silently deleted the rest of the line (#1067
    review).

    Each block's preview is bounded by ``_TOOL_PREVIEW_LEN``, so the joined
    value is bounded by the block count, which is bounded by the raw line -
    already returned in full and unbounded as ``ConversationLine.raw``.
    """
    top_type = data.get("type")
    if top_type not in ("assistant", "user"):
        return None
    message = data.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return None

    tool_names: list[str] = []
    previews: list[str] = []
    saw_tool_use = False
    saw_tool_block = False

    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "tool_use":
            saw_tool_block = True
            saw_tool_use = True
            name = item.get("name")
            if isinstance(name, str) and name:
                tool_names.append(name)
            input_data = item.get("input")
            preview = _claude_tool_use_preview(input_data) if isinstance(input_data, dict) else None
            if preview:
                previews.append(preview)
        elif item_type == "tool_result":
            saw_tool_block = True
            preview = _claude_tool_result_preview(item)
            if preview:
                previews.append(preview)

    if not saw_tool_block:
        return None

    # A line holding any tool_use renders as a tool row; a line holding only
    # tool_results keeps its own top-level type, as before this change.
    event_type = TranscriptEventType.TOOL_USE if saw_tool_use else str(top_type)
    return (
        event_type,
        _TOOL_FIELD_SEP.join(tool_names) or None,
        _TOOL_FIELD_SEP.join(previews) or None,
    )


_CODEX_TOOL_ITEM_TYPES = frozenset((CodexItemType.COMMAND_EXECUTION, CodexItemType.FILE_CHANGE))


def _codex_item_fields(
    item: Mapping[str, object], stream_type: CodexStreamType
) -> tuple[str, str | None, str | None]:
    """Map a codex stream ``item`` to (event_type, tool_name, preview).

    Codex emits both ``item.started`` and ``item.completed`` for the same
    tool call. Only ``item.completed`` renders a tool row - ``item.started``
    is normalized to a plain ``system`` line with no tool_name/preview, so
    the raw line still appears (expandable) but never duplicates the
    completed row, whether or not the completed side has output.
    """
    item_type = item.get("type")
    if item_type == CodexItemType.AGENT_MESSAGE:
        text = item.get("text")
        preview = text[:_PREVIEW_LEN] if isinstance(text, str) and text else None
        return TranscriptEventType.ASSISTANT, None, preview
    if item_type in _CODEX_TOOL_ITEM_TYPES and stream_type == CodexStreamType.ITEM_STARTED:
        return TranscriptEventType.SYSTEM, None, None
    if item_type == CodexItemType.COMMAND_EXECUTION:
        return (
            TranscriptEventType.TOOL_USE,
            CODEX_TOOL_NAME_COMMAND,
            _codex_command_execution_preview(item),
        )
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

    claude_tool = _extract_claude_tool_fields(data)
    if claude_tool is not None:
        return claude_tool

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
