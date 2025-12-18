"""Session API endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query

from aef_adapters.projections import get_projection_manager
from aef_dashboard.models.schemas import (
    OperationInfo,
    SessionResponse,
    SessionSummary,
)
from aef_domain.contexts.sessions.domain.queries import ListSessionsQuery
from aef_domain.contexts.sessions.slices.list_sessions import ListSessionsHandler

if TYPE_CHECKING:
    from aef_domain.contexts.sessions.domain.read_models import (
        SessionSummary as DomainSessionSummary,
    )

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _domain_session_to_api(session: DomainSessionSummary) -> SessionSummary:
    """Convert domain SessionSummary to API SessionSummary."""
    return SessionSummary(
        id=session.id,
        workflow_id=session.workflow_id,
        execution_id=session.execution_id,
        phase_id=session.phase_id,
        status=session.status,
        agent_provider=session.agent_type,
        total_tokens=session.total_tokens,
        total_cost_usd=session.total_cost_usd,
        started_at=session.started_at,
        completed_at=session.completed_at,
    )


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    workflow_id: str | None = Query(None, description="Filter by workflow ID"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
) -> list[SessionSummary]:
    """List agent sessions with optional filtering."""
    # Get projection manager and create handler
    manager = get_projection_manager()
    handler = ListSessionsHandler(manager.session_list)

    # Build and execute query
    query = ListSessionsQuery(
        workflow_id=workflow_id,
        status_filter=status,
        limit=limit,
    )
    sessions = await handler.handle(query)

    return [_domain_session_to_api(s) for s in sessions]


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    """Get session details by ID."""
    # Get projection manager and create handler
    manager = get_projection_manager()
    handler = ListSessionsHandler(manager.session_list)

    # Query all sessions and find the matching one
    # TODO: Add a GetSessionDetailQuery for direct lookup
    query = ListSessionsQuery(limit=10000)
    sessions = await handler.handle(query)
    session = next((s for s in sessions if s.id == session_id), None)

    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    # Get execution_id for TimescaleDB queries
    # Observability data is stored with execution_id as session_id in TimescaleDB
    execution_id = getattr(session, "execution_id", None)
    timescale_session_id = execution_id or session_id

    # Get cost data from TimescaleDB via SessionCostProjection
    session_cost = await manager.session_cost.get_session_cost(timescale_session_id)

    # Get workspace_path from execution_started event (ADR-029)
    workspace_path: str | None = None
    try:
        from aef_adapters.events import get_event_store

        store = get_event_store()
        await store.initialize()
        if store.pool:
            async with store.pool.acquire() as conn:
                result = await conn.fetchval(
                    """
                    SELECT data->>'workspace_path'
                    FROM agent_events
                    WHERE session_id = $1 AND event_type = 'execution_started'
                    ORDER BY time DESC
                    LIMIT 1
                    """,
                    timescale_session_id,
                )
                workspace_path = result
    except Exception:
        pass  # Workspace path is optional

    # Get tool operations from TimescaleDB via SessionToolsProjection (ADR-026)
    tool_operations = await manager.session_tools.get(timescale_session_id)

    # Convert ToolOperation read models to API OperationInfo
    operations: list[OperationInfo] = []
    for tool_op in tool_operations:
        # Handle input_preview - may be a string that needs parsing
        tool_input_dict: dict[str, Any] | None = None
        if tool_op.input_preview:
            import json as json_module

            try:
                parsed = json_module.loads(tool_op.input_preview)
                if isinstance(parsed, dict):
                    tool_input_dict = parsed
                else:
                    tool_input_dict = {"raw": tool_op.input_preview}
            except (json_module.JSONDecodeError, TypeError):
                tool_input_dict = {"raw": tool_op.input_preview}

        operations.append(
            OperationInfo(
                operation_id=tool_op.observation_id,
                operation_type=tool_op.operation_type,
                timestamp=tool_op.timestamp,
                duration_seconds=(tool_op.duration_ms / 1000.0) if tool_op.duration_ms else None,
                success=tool_op.success if tool_op.success is not None else True,
                # Token metrics (not available in tool operations)
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                # Tool details
                tool_name=tool_op.tool_name,
                tool_use_id=tool_op.tool_use_id,
                tool_input=tool_input_dict,
                tool_output=tool_op.output_preview,
                # Message details (not applicable for tool ops)
                message_role=None,
                message_content=None,
                # Thinking details (not applicable for tool ops)
                thinking_content=None,
            )
        )

    # Fallback to projection if TimescaleDB doesn't have data
    if not operations:
        for op in session.operations:
            # Handle timestamp - can be string or datetime
            ts = op.timestamp
            if isinstance(ts, str):
                from datetime import datetime as dt

                try:
                    ts = dt.fromisoformat(ts.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    ts = None
            operations.append(
                OperationInfo(
                    operation_id=op.operation_id,
                    operation_type=op.operation_type,
                    timestamp=ts,
                    duration_seconds=op.duration_seconds,
                    success=op.success,
                    # Token metrics
                    input_tokens=op.input_tokens,
                    output_tokens=op.output_tokens,
                    total_tokens=op.total_tokens,
                    # Tool details
                    tool_name=op.tool_name,
                    tool_use_id=op.tool_use_id,
                    tool_input=op.tool_input,
                    tool_output=op.tool_output,
                    # Message details
                    message_role=op.message_role,
                    message_content=op.message_content,
                    # Thinking details
                    thinking_content=op.thinking_content,
                )
            )

    # Get workflow name from projection if available
    workflow_name = None
    if session.workflow_id:
        try:
            # Try to get workflow from the list projection
            workflows = await manager.workflow_list.get_all()
            wf = next((w for w in workflows if w.id == session.workflow_id), None)
            if wf:
                workflow_name = wf.name
        except Exception:
            pass  # workflow lookup is optional

    # Use cost data from TimescaleDB if available, otherwise use session data
    if session_cost:
        input_tokens = session_cost.input_tokens
        output_tokens = session_cost.output_tokens
        total_tokens = input_tokens + output_tokens
        total_cost_usd = session_cost.total_cost_usd
    else:
        input_tokens = session.input_tokens
        output_tokens = session.output_tokens
        total_tokens = session.total_tokens
        total_cost_usd = Decimal(str(session.total_cost_usd))

    return SessionResponse(
        id=session.id,
        workflow_id=session.workflow_id,
        workflow_name=workflow_name,
        execution_id=getattr(session, "execution_id", None),
        phase_id=session.phase_id,
        milestone_id=None,
        agent_provider=session.agent_type,
        agent_model=None,
        status=session.status,
        workspace_path=workspace_path,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        total_cost_usd=total_cost_usd,
        operations=operations,
        started_at=session.started_at,
        completed_at=session.completed_at,
        duration_seconds=session.duration_seconds,
        error_message=None,
        metadata={},
    )
