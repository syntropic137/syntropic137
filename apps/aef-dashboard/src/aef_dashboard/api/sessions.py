"""Session API endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

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

    # Convert operations from projection to API model
    operations = []
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
                input_tokens=op.input_tokens,
                output_tokens=op.output_tokens,
                total_tokens=op.total_tokens,
                tool_name=op.tool_name,
                success=op.success,
            )
        )

    return SessionResponse(
        id=session.id,
        workflow_id=session.workflow_id,
        phase_id=session.phase_id,
        milestone_id=None,
        agent_provider=session.agent_type,
        agent_model=None,
        status=session.status,
        input_tokens=session.input_tokens,
        output_tokens=session.output_tokens,
        total_tokens=session.total_tokens,
        total_cost_usd=Decimal(str(session.total_cost_usd)),
        operations=operations,
        started_at=session.started_at,
        completed_at=session.completed_at,
        duration_seconds=session.duration_seconds,
        error_message=None,
        metadata={},
    )
