"""Event API endpoints — thin wrapper over v1."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import syn_api.v1.observability as obs
from syn_api.types import Err

router = APIRouter(prefix="/events", tags=["events"])


# ============================================================================
# Response Models
# ============================================================================


class EventResponse(BaseModel):
    """Single event response."""

    time: Any
    event_type: str
    session_id: str | None = None
    execution_id: str | None = None
    phase_id: str | None = None
    data: dict[str, Any] = {}


class EventListResponse(BaseModel):
    """List of events response."""

    events: list[EventResponse]
    count: int
    has_more: bool = False


class TimelineEntry(BaseModel):
    """Timeline entry for visualization."""

    time: Any
    event_type: str
    tool_name: str | None = None
    duration_ms: int | None = None
    success: bool | None = None


class CostSummary(BaseModel):
    """Cost summary for a session."""

    session_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    estimated_cost_usd: float | None = None


class ToolSummary(BaseModel):
    """Tool usage summary."""

    tool_name: str
    call_count: int
    success_count: int
    error_count: int
    total_duration_ms: int
    avg_duration_ms: float


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/recent", response_model=EventListResponse)
async def get_recent_activity(
    limit: int = Query(50, ge=1, le=200, description="Max events to return"),
) -> EventListResponse:
    """Get recent git activity events for the global dashboard feed."""
    result = await obs.get_recent_activity_events(limit=limit)

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=f"Failed to query activity: {result.message}")

    events = result.value
    return EventListResponse(
        events=[
            EventResponse(
                time=e["time"],
                event_type=e["event_type"],
                session_id=e.get("session_id"),
                execution_id=e.get("execution_id"),
                data=e.get("data", {}),
            )
            for e in events
        ],
        count=len(events),
    )


@router.get("/sessions/{session_id}", response_model=EventListResponse)
async def get_session_events(
    session_id: str,
    event_type: str | None = Query(None, description="Filter by event type"),
    limit: int = Query(100, ge=1, le=1000, description="Max events to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> EventListResponse:
    """Get all events for a session."""
    result = await obs.get_session_events(
        session_id=session_id,
        event_type=event_type,
        limit=limit + 1,
        offset=offset,
    )

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=f"Failed to query events: {result.message}")

    events = result.value
    has_more = len(events) > limit
    if has_more:
        events = events[:limit]

    return EventListResponse(
        events=[
            EventResponse(
                time=e.time,
                event_type=e.event_type,
                session_id=e.session_id,
                execution_id=e.execution_id,
                phase_id=e.phase_id,
                data=e.data,
            )
            for e in events
        ],
        count=len(events),
        has_more=has_more,
    )


@router.get("/sessions/{session_id}/timeline", response_model=list[TimelineEntry])
async def get_session_timeline(
    session_id: str,
    limit: int = Query(100, ge=1, le=500, description="Max entries"),
) -> list[TimelineEntry]:
    """Get a timeline view of session events."""
    result = await obs.get_session_timeline(session_id=session_id, limit=limit)

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=f"Failed to get timeline: {result.message}")

    return [
        TimelineEntry(
            time=e.time,
            event_type=e.event_type,
            tool_name=e.tool_name,
            duration_ms=int(e.duration_ms) if e.duration_ms else None,
            success=e.success,
        )
        for e in result.value
    ]


@router.get("/sessions/{session_id}/costs", response_model=CostSummary)
async def get_session_costs(session_id: str) -> CostSummary:
    """Get cost summary for a session."""
    result = await obs.get_token_metrics(session_id=session_id)

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=f"Failed to get costs: {result.message}")

    data = result.value
    return CostSummary(
        session_id=session_id,
        input_tokens=data.get("input_tokens", 0),
        output_tokens=data.get("output_tokens", 0),
        total_tokens=data.get("total_tokens", 0),
        cache_creation_tokens=data.get("cache_creation_tokens", 0),
        cache_read_tokens=data.get("cache_read_tokens", 0),
        estimated_cost_usd=float(data["total_cost_usd"]) if "total_cost_usd" in data else None,
    )


@router.get("/sessions/{session_id}/tools", response_model=list[ToolSummary])
async def get_session_tools(session_id: str) -> list[ToolSummary]:
    """Get tool usage summary for a session."""
    result = await obs.get_session_tool_summary(session_id=session_id)

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=f"Failed to get tools: {result.message}")

    return [
        ToolSummary(
            tool_name=t.tool_name,
            call_count=t.call_count,
            success_count=t.success_count,
            error_count=t.error_count,
            total_duration_ms=int(t.total_duration_ms),
            avg_duration_ms=(t.total_duration_ms / t.call_count if t.call_count > 0 else 0.0),
        )
        for t in result.value
    ]
