"""Session API endpoints."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query

from aef_dashboard.models.schemas import (
    SessionResponse,
    SessionSummary,
)
from aef_dashboard.read_models import SessionReadModel, get_all_sessions

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _session_to_summary(session: SessionReadModel) -> SessionSummary:
    """Convert a SessionReadModel to a SessionSummary."""
    return SessionSummary(
        id=session.id,
        workflow_id=session.workflow_id,
        phase_id=session.phase_id,
        status=session.status,
        agent_provider=session.agent_provider,
        total_tokens=session.total_tokens,
        total_cost_usd=Decimal(str(session.total_cost_usd)),
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
    sessions = await get_all_sessions()

    # Filter by workflow_id if provided
    if workflow_id:
        sessions = [s for s in sessions if s.workflow_id == workflow_id]

    # Filter by status if provided
    if status:
        sessions = [s for s in sessions if s.status == status]

    # Apply limit
    sessions = sessions[:limit]

    return [_session_to_summary(s) for s in sessions]


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    """Get session details by ID."""
    sessions = await get_all_sessions()
    session = next((s for s in sessions if s.id == session_id), None)

    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return SessionResponse(
        id=session.id,
        workflow_id=session.workflow_id,
        phase_id=session.phase_id,
        milestone_id=None,
        agent_provider=session.agent_provider,
        agent_model=None,
        status=session.status,
        input_tokens=0,
        output_tokens=0,
        total_tokens=session.total_tokens,
        total_cost_usd=Decimal(str(session.total_cost_usd)),
        operations=[],
        started_at=session.started_at,
        completed_at=session.completed_at,
        duration_seconds=None,
        error_message=None,
        metadata={},
    )
