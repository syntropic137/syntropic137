"""Conversation log API endpoints and service operations.

Provides retrieval of session conversation logs from MinIO storage.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, computed_field

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import ConversationLogReader

from syn_api._wiring import (
    ensure_connected,
    get_conversation_log_reader,
    get_conversation_store,
    get_projection_mgr,
)
from syn_api.model_identity import ObservedModelId, observed_model_of
from syn_api.types import (
    ConversationLine,
    ConversationLog,
    ConversationMeta,
    Err,
    ObservabilityError,
    Ok,
    Result,
)
from syn_domain.contexts.agent_sessions import AgentLaunch
from syn_shared.observed_model import format_observed_model

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
    model: ObservedModelId | None = None
    """The model the harness REPORTED for this conversation, or null.

    Never an alias (ADR-067 D9): what the phase asked for is ``requested_model``.
    """
    requested_model: str | None = None
    """The model the phase REQUESTED (often an alias such as ``opus``), or null."""
    success: bool | None = None
    size_bytes: int | None = None

    @computed_field(
        description="The model for humans: the reported id verbatim, or "
        "'<alias> (requested)', or 'unknown' (ADR-067 D9)."
    )
    @property
    def model_display(self) -> str:
        """Derived, never passed in, so it cannot contradict ``model``."""
        return format_observed_model(self.model, self.requested_model)


# =============================================================================
# Service functions (importable by tests)
# =============================================================================


def _conversation_line(
    reader: ConversationLogReader, line_number: int, raw: str
) -> ConversationLine:
    """One stored line as a numbered ``ConversationLine``, read through the port."""
    row = reader.read_row(raw)
    return ConversationLine(
        line_number=line_number,
        raw=raw,
        event_type=row.event_type,
        tool_name=row.tool_name,
        content_preview=row.content_preview,
    )


async def _classify_missing_conversation(session_id: str) -> ObservabilityError:
    """Classify why a conversation log is missing for this session.

    A ``session_summaries`` row exists once ``StartSessionCommand`` succeeds
    (SessionListProjection.on_session_started), so its absence here doesn't
    itself mean "never started" - the caller already resolved this session_id
    against that same projection to get this far.

    ``agent_launch`` is the domain fact carried by ``AgentLaunchedEvent`` and
    ``SessionCompletedEvent``, reported by the agent's own output stream once
    the process is known to exist. It is the only thing that discriminates "no
    agent ever ran" from "an agent ran and later failed/was cancelled": both
    leave ``total_tokens == 0`` on every failure/cancellation path, so status
    and tokens alone can't tell them apart (issue #1047, #1065).

    Only ``NOT_LAUNCHED`` earns NEVER_STARTED. ``UNKNOWN`` - a row from a
    stream written before the fact existed, or one whose launch write has not
    landed yet - says nothing, and a row that says nothing must not be quoted
    as saying no. It falls through to the generic NOT_FOUND, which is what
    every such session got before the fact existed at all.

    A session still ``running`` is neither of those - it may not have
    produced a log yet regardless of whether the agent has launched, so it
    gets its own PENDING classification rather than being folded into either
    terminal case.
    """
    mgr = get_projection_mgr()
    data = await mgr.store.get("session_summaries", session_id)
    if data is None:
        return ObservabilityError.NOT_FOUND

    if data.get("status") == "running":
        return ObservabilityError.PENDING

    if AgentLaunch.read(data.get("agent_launch")) is AgentLaunch.NOT_LAUNCHED:
        return ObservabilityError.NEVER_STARTED

    return ObservabilityError.NOT_FOUND


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
            classification = await _classify_missing_conversation(session_id)
            if classification == ObservabilityError.NEVER_STARTED:
                return Err(
                    ObservabilityError.NEVER_STARTED,
                    message=(
                        f"Session {session_id} never started an agent, so no "
                        "conversation was ever recorded."
                    ),
                )
            if classification == ObservabilityError.PENDING:
                return Err(
                    ObservabilityError.PENDING,
                    message=(
                        f"Session {session_id} is still running; no conversation "
                        "log has been recorded yet."
                    ),
                )
            return Err(
                ObservabilityError.NOT_FOUND,
                message=f"Conversation log not found for session {session_id}",
            )

        # Drop harness CLI chrome before numbering so line numbers and
        # total_lines reflect only real transcript content.
        reader = get_conversation_log_reader()
        raw_lines = [line for line in raw_lines if reader.belongs_in_log(line)]

        total = len(raw_lines)
        page = raw_lines[offset : offset + limit]
        lines = [_conversation_line(reader, i, raw) for i, raw in enumerate(page, start=offset + 1)]

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

        # The index classifies its own legacy rows, but a store that does not
        # (or a row written before it did) can still hand back the REQUESTED
        # alias as ``model``: it is served as the request, never as what ran.
        recorded = observed_model_of(meta.get("model"), meta.get("requested_model"))
        return Ok(
            ConversationMeta(
                session_id=session_id,
                event_count=meta.get("event_count", 0),
                model=recorded.observed,
                requested_model=recorded.requested,
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
        if result.error == ObservabilityError.NEVER_STARTED:
            raise HTTPException(status_code=404, detail=result.message)
        if result.error == ObservabilityError.PENDING:
            raise HTTPException(status_code=404, detail=result.message)
        if result.error == ObservabilityError.NOT_FOUND:
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
        requested_model=meta.requested_model,
        size_bytes=meta.size_bytes,
        execution_id=meta.execution_id,
        workflow_id=meta.workflow_id,
        phase_id=meta.phase_id,
        success=meta.success,
    )
