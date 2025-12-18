"""Event API endpoints for querying agent events.

These endpoints provide access to raw JSONL events from agent executions,
stored in the agent_events TimescaleDB hypertable (ADR-029).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

if TYPE_CHECKING:
    from datetime import datetime

router = APIRouter(prefix="/events", tags=["events"])


# ============================================================================
# Response Models
# ============================================================================


class EventResponse(BaseModel):
    """Single event response."""

    time: datetime
    event_type: str
    session_id: str
    execution_id: str | None = None
    phase_id: str | None = None
    data: dict[str, Any]


class EventListResponse(BaseModel):
    """List of events response."""

    events: list[EventResponse]
    count: int
    has_more: bool = False


class TimelineEntry(BaseModel):
    """Timeline entry for visualization."""

    time: datetime
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
    # Cost calculation would need pricing info
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


@router.get("/sessions/{session_id}", response_model=EventListResponse)
async def get_session_events(
    session_id: str,
    event_type: str | None = Query(None, description="Filter by event type"),
    limit: int = Query(100, ge=1, le=1000, description="Max events to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> EventListResponse:
    """Get all events for a session."""
    try:
        from aef_adapters.events import get_event_store

        store = get_event_store()
        await store.initialize()

        events = await store.query(
            session_id=session_id,
            event_type=event_type,
            limit=limit + 1,  # Fetch one extra to check has_more
            offset=offset,
        )

        has_more = len(events) > limit
        if has_more:
            events = events[:limit]

        return EventListResponse(
            events=[
                EventResponse(
                    time=e["time"],
                    event_type=e["event_type"],
                    session_id=e["session_id"],
                    execution_id=e.get("execution_id"),
                    phase_id=e.get("phase_id"),
                    data=e.get("data", {}),
                )
                for e in events
            ],
            count=len(events),
            has_more=has_more,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query events: {e}") from e


@router.get("/sessions/{session_id}/timeline", response_model=list[TimelineEntry])
async def get_session_timeline(
    session_id: str,
    limit: int = Query(100, ge=1, le=500, description="Max entries"),
) -> list[TimelineEntry]:
    """Get a timeline view of session events.

    Returns tool executions and key events in chronological order.
    """
    try:
        from aef_adapters.events import get_event_store

        store = get_event_store()
        await store.initialize()

        # Get tool events for timeline
        events = await store.query(
            session_id=session_id,
            limit=limit * 2,  # Get more to filter
        )

        timeline: list[TimelineEntry] = []
        for e in events:
            event_type = e["event_type"]
            data = e.get("data", {})

            # Include key event types in timeline
            if event_type in (
                "tool_execution_started",
                "tool_execution_completed",
                "session_started",
                "session_completed",
                "security_decision",
            ):
                timeline.append(
                    TimelineEntry(
                        time=e["time"],
                        event_type=event_type,
                        tool_name=data.get("tool_name"),
                        duration_ms=data.get("duration_ms"),
                        success=data.get("success"),
                    )
                )

        return timeline[:limit]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get timeline: {e}") from e


@router.get("/sessions/{session_id}/costs", response_model=CostSummary)
async def get_session_costs(session_id: str) -> CostSummary:
    """Get cost summary for a session.

    Aggregates token usage from all events in the session.
    """
    try:
        from aef_adapters.events import get_event_store

        store = get_event_store()
        await store.initialize()

        # Query for token usage events
        events = await store.query(
            session_id=session_id,
            event_type="token_usage",
            limit=10000,  # Get all token events
        )

        # Aggregate token counts
        input_tokens = 0
        output_tokens = 0
        cache_creation = 0
        cache_read = 0

        for e in events:
            data = e.get("data", {})
            input_tokens += data.get("input_tokens", 0)
            output_tokens += data.get("output_tokens", 0)
            cache_creation += data.get("cache_creation_tokens", 0)
            cache_read += data.get("cache_read_tokens", 0)

        return CostSummary(
            session_id=session_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
            # TODO: Calculate cost based on model pricing
            estimated_cost_usd=None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get costs: {e}") from e


@router.get("/sessions/{session_id}/tools", response_model=list[ToolSummary])
async def get_session_tools(session_id: str) -> list[ToolSummary]:
    """Get tool usage summary for a session.

    Returns aggregated stats for each tool used in the session.
    """
    try:
        from aef_adapters.events import get_event_store

        store = get_event_store()
        await store.initialize()

        # Query for tool completion events
        events = await store.query(
            session_id=session_id,
            event_type="tool_execution_completed",
            limit=10000,
        )

        # Aggregate by tool name
        tool_stats: dict[str, dict[str, Any]] = {}

        for e in events:
            data = e.get("data", {})
            tool_name = data.get("tool_name", "unknown")

            if tool_name not in tool_stats:
                tool_stats[tool_name] = {
                    "call_count": 0,
                    "success_count": 0,
                    "error_count": 0,
                    "total_duration_ms": 0,
                }

            stats = tool_stats[tool_name]
            stats["call_count"] += 1

            if data.get("success", True):
                stats["success_count"] += 1
            else:
                stats["error_count"] += 1

            duration = data.get("duration_ms", 0)
            if isinstance(duration, int | float):
                stats["total_duration_ms"] += int(duration)

        # Build response
        return [
            ToolSummary(
                tool_name=name,
                call_count=stats["call_count"],
                success_count=stats["success_count"],
                error_count=stats["error_count"],
                total_duration_ms=stats["total_duration_ms"],
                avg_duration_ms=(
                    stats["total_duration_ms"] / stats["call_count"]
                    if stats["call_count"] > 0
                    else 0.0
                ),
            )
            for name, stats in sorted(tool_stats.items())
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get tools: {e}") from e
