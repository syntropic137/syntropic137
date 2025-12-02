"""Session API endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query

from aef_adapters.storage import get_session_repository
from aef_dashboard.models.schemas import (
    OperationInfo,
    SessionResponse,
    SessionSummary,
)

if TYPE_CHECKING:
    from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
        AgentSessionAggregate,
    )

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _session_to_summary(session: AgentSessionAggregate) -> SessionSummary:
    """Convert an AgentSessionAggregate to a SessionSummary."""
    return SessionSummary(
        id=str(session.id) if session.id else "",
        workflow_id=session.workflow_id,
        phase_id=session.phase_id,
        status=session.status.value if session.status else "unknown",
        agent_provider=session._agent_provider,
        total_tokens=session.tokens.total_tokens if session.tokens else 0,
        total_cost_usd=session.cost.total_cost_usd if session.cost else Decimal("0"),
        started_at=session._started_at,
        completed_at=session._completed_at,
    )


def _session_to_response(session: AgentSessionAggregate) -> SessionResponse:
    """Convert an AgentSessionAggregate to a SessionResponse."""
    operations = [
        OperationInfo(
            operation_id=op.operation_id,
            operation_type=op.operation_type.value,
            timestamp=op.timestamp,
            duration_seconds=op.duration_seconds,
            input_tokens=op.tokens.input_tokens if op.tokens else None,
            output_tokens=op.tokens.output_tokens if op.tokens else None,
            total_tokens=op.tokens.total_tokens if op.tokens else None,
            tool_name=op.tool_name,
            success=op.success,
        )
        for op in (session.operations or [])
    ]

    return SessionResponse(
        id=str(session.id) if session.id else "",
        workflow_id=session.workflow_id,
        phase_id=session.phase_id,
        milestone_id=session._milestone_id,
        agent_provider=session._agent_provider,
        agent_model=session._agent_model,
        status=session.status.value if session.status else "unknown",
        input_tokens=session.tokens.input_tokens if session.tokens else 0,
        output_tokens=session.tokens.output_tokens if session.tokens else 0,
        total_tokens=session.tokens.total_tokens if session.tokens else 0,
        total_cost_usd=session.cost.total_cost_usd if session.cost else Decimal("0"),
        operations=operations,
        started_at=session._started_at,
        completed_at=session._completed_at,
        duration_seconds=session.duration_seconds,
        error_message=None,  # Error message not tracked in current aggregate
        metadata=session._metadata or {},
    )


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    workflow_id: str | None = Query(None, description="Filter by workflow ID"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
) -> list[SessionSummary]:
    """List agent sessions with optional filtering."""
    repo = get_session_repository()
    sessions = repo.get_by_workflow(workflow_id) if workflow_id else repo.get_all()

    # Filter by status if provided
    if status:
        sessions = [s for s in sessions if s.status and s.status.value == status]

    # Apply limit
    sessions = sessions[:limit]

    return [_session_to_summary(s) for s in sessions]


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    """Get session details by ID."""
    repo = get_session_repository()
    session = await repo.get(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return _session_to_response(session)
