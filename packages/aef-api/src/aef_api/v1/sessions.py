"""Session operations — list, start, and complete agent sessions.

Maps to the agent_sessions context in aef-domain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aef_api._wiring import (
    ensure_connected,
    get_projection_mgr,
    get_session_repo,
    sync_published_events_to_projections,
)
from aef_api.types import Err, Ok, Result, SessionError, SessionSummary

if TYPE_CHECKING:
    from aef_api.auth import AuthContext


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
    from aef_domain.contexts.agent_sessions.slices.start_session.StartSessionHandler import (
        StartSessionHandler,
    )

    await ensure_connected()
    repository = get_session_repo()
    handler = StartSessionHandler(repository=repository)

    try:
        from aef_domain.contexts.agent_sessions.domain.commands.StartSessionCommand import (
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
    from aef_domain.contexts.agent_sessions.slices.complete_session.CompleteSessionHandler import (
        CompleteSessionHandler,
    )

    await ensure_connected()
    repository = get_session_repo()
    handler = CompleteSessionHandler(repository=repository)

    try:
        from aef_domain.contexts.agent_sessions.domain.commands.CompleteSessionCommand import (
            CompleteSessionCommand,
        )

        command = CompleteSessionCommand(aggregate_id=session_id)
        await handler.handle(command)
        return Ok(None)
    except Exception as e:
        return Err(SessionError.NOT_FOUND, message=str(e))
