"""Session operations — list, start, and complete agent sessions.

Maps to the agent_sessions context in syn-domain.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_api._wiring import (
    ensure_connected,
    get_projection_mgr,
    get_session_repo,
    sync_published_events_to_projections,
)
from syn_api.types import (
    Err,
    Ok,
    Result,
    SessionDetail,
    SessionError,
    SessionSummary,
    ToolOperation,
)

if TYPE_CHECKING:
    from syn_api.auth import AuthContext

logger = logging.getLogger(__name__)


async def list_sessions(
    workflow_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[SessionSummary], SessionError]:
    """List agent sessions, optionally filtered.

    Args:
        workflow_id: Filter by workflow ID.
        status: Filter by session status.
        limit: Maximum results to return.
        offset: Pagination offset.
        auth: Optional authentication context.

    Returns:
        Ok(list[SessionSummary]) on success, Err(SessionError) on failure.
    """
    await ensure_connected()
    manager = get_projection_mgr()
    projection = manager.session_list
    domain_sessions = await projection.query(
        workflow_id=workflow_id,
        status_filter=status,
        limit=limit,
        offset=offset,
    )
    return Ok(
        [
            SessionSummary(
                id=s.id,
                workflow_id=s.workflow_id,
                execution_id=s.execution_id,
                phase_id=s.phase_id,
                status=s.status,
                agent_type=s.agent_type,
                total_tokens=s.total_tokens,
                total_cost_usd=s.total_cost_usd,
                started_at=s.started_at,
                completed_at=s.completed_at,
            )
            for s in domain_sessions
        ]
    )


async def start_session(
    workflow_id: str,
    phase_id: str | None = None,
    execution_id: str | None = None,
    agent_type: str = "claude",
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[str, SessionError]:
    """Start a new agent session.

    Args:
        workflow_id: The workflow this session belongs to.
        phase_id: Optional phase within the workflow.
        execution_id: Optional execution ID.
        agent_type: The agent provider (default: claude).
        auth: Optional authentication context.

    Returns:
        Ok(session_id) on success, Err(SessionError) on failure.
    """
    from syn_domain.contexts.agent_sessions.slices.start_session.StartSessionHandler import (
        StartSessionHandler,
    )

    await ensure_connected()
    repository = get_session_repo()
    handler = StartSessionHandler(repository=repository)

    try:
        from syn_domain.contexts.agent_sessions.domain.commands.StartSessionCommand import (
            StartSessionCommand,
        )

        command = StartSessionCommand(
            workflow_id=workflow_id,
            phase_id=phase_id or "",
            execution_id=execution_id or "",
            agent_provider=agent_type,
        )
        session_id = await handler.handle(command)
        await sync_published_events_to_projections()
        return Ok(session_id)
    except Exception as e:
        return Err(SessionError.INVALID_INPUT, message=str(e))


async def complete_session(
    session_id: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[None, SessionError]:
    """Complete an agent session.

    Args:
        session_id: The session to complete.
        auth: Optional authentication context.

    Returns:
        Ok(None) on success, Err(SessionError) on failure.
    """
    from syn_domain.contexts.agent_sessions.slices.complete_session.CompleteSessionHandler import (
        CompleteSessionHandler,
    )

    await ensure_connected()
    repository = get_session_repo()
    handler = CompleteSessionHandler(repository=repository)

    try:
        from syn_domain.contexts.agent_sessions.domain.commands.CompleteSessionCommand import (
            CompleteSessionCommand,
        )

        command = CompleteSessionCommand(aggregate_id=session_id)
        await handler.handle(command)
        return Ok(None)
    except Exception as e:
        return Err(SessionError.NOT_FOUND, message=str(e))


async def get_session(
    session_id: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[SessionDetail, SessionError]:
    """Get detailed information about a session, including tool operations and costs.

    Args:
        session_id: The session ID to look up.
        auth: Optional authentication context.

    Returns:
        Ok(SessionDetail) on success, Err(SessionError.NOT_FOUND) if missing.
    """
    await ensure_connected()
    manager = get_projection_mgr()

    # Look up session in the session_list projection
    sessions = await manager.session_list.query(limit=10000)
    session = next((s for s in sessions if s.id == session_id), None)

    if session is None:
        return Err(SessionError.NOT_FOUND, message=f"Session {session_id} not found")

    # Get tool operations
    operations: list[ToolOperation] = []
    try:
        tool_data = await manager.session_tools.get(session_id)
        operations = [
            ToolOperation(
                observation_id=getattr(op, "observation_id", ""),
                operation_type=getattr(op, "operation_type", ""),
                timestamp=getattr(op, "timestamp", None),
                duration_ms=getattr(op, "duration_ms", None),
                success=getattr(op, "success", None),
                tool_name=getattr(op, "tool_name", None),
                tool_use_id=getattr(op, "tool_use_id", None),
                input_preview=getattr(op, "input_preview", None),
                output_preview=getattr(op, "output_preview", None),
                git_sha=getattr(op, "git_sha", None),
                git_message=getattr(op, "git_message", None),
                git_branch=getattr(op, "git_branch", None),
            )
            for op in (tool_data or [])
        ]
    except Exception:
        logger.exception("Failed to load tool operations for session %s", session_id)

    # Get cost data
    input_tokens = 0
    output_tokens = 0
    total_cost = session.total_cost_usd
    duration_seconds = None
    try:
        cost = await manager.session_cost.get_session_cost(session_id)
        if cost:
            input_tokens = getattr(cost, "input_tokens", 0)
            output_tokens = getattr(cost, "output_tokens", 0)
            total_cost = getattr(cost, "total_cost_usd", session.total_cost_usd)
            if getattr(cost, "duration_ms", 0):
                duration_seconds = getattr(cost, "duration_ms", 0) / 1000.0
    except Exception:
        logger.exception("Failed to load cost data for session %s", session_id)

    return Ok(
        SessionDetail(
            id=session.id,
            workflow_id=session.workflow_id,
            execution_id=session.execution_id,
            phase_id=session.phase_id,
            agent_type=session.agent_type,
            status=session.status,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=session.total_tokens,
            total_cost_usd=total_cost,
            operations=operations,
            started_at=session.started_at,
            completed_at=session.completed_at,
            duration_seconds=duration_seconds,
        )
    )
