"""Observability operations — tool timelines, token metrics, events.

Provides access to execution telemetry and cost tracking data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aef_api._wiring import ensure_connected, get_event_store_instance, get_projection_mgr
from aef_api.types import (
    Err,
    EventRecord,
    ObservabilityError,
    Ok,
    Result,
    TimelineEntry,
    ToolUsageSummary,
)

if TYPE_CHECKING:
    from aef_api.auth import AuthContext


async def get_tool_timeline(
    session_id: str,
    limit: int = 1000,
    include_blocked: bool = False,
    auth: AuthContext | None = None,
) -> Result[list[dict[str, Any]], ObservabilityError]:
    """Get the tool call timeline for a session.

    Args:
        session_id: The session to get the timeline for.
        limit: Maximum events to return.
        include_blocked: Include blocked tool calls.
        auth: Optional authentication context.

    Returns:
        Ok(list[dict]) with timeline events on success.
    """
    await ensure_connected()
    try:
        manager = get_projection_mgr()
        projection = manager.session_tools
        operations = await projection.get(session_id)

        result = []
        for op in (operations or [])[:limit]:
            result.append(
                {
                    "observation_id": getattr(op, "observation_id", ""),
                    "operation_type": getattr(op, "operation_type", ""),
                    "tool_name": getattr(op, "tool_name", None),
                    "timestamp": str(getattr(op, "timestamp", "")),
                    "duration_ms": getattr(op, "duration_ms", None),
                    "success": getattr(op, "success", None),
                }
            )
        return Ok(result)
    except Exception as e:
        return Err(ObservabilityError.QUERY_FAILED, message=str(e))


async def get_token_metrics(
    execution_id: str | None = None,
    session_id: str | None = None,
    auth: AuthContext | None = None,
) -> Result[dict[str, Any], ObservabilityError]:
    """Get token usage metrics for an execution or session.

    Args:
        execution_id: Filter by execution ID.
        session_id: Filter by session ID.
        auth: Optional authentication context.

    Returns:
        Ok(dict) with token metrics on success.
    """
    await ensure_connected()
    try:
        manager = get_projection_mgr()

        if session_id:
            cost = await manager.session_cost.get_session_cost(session_id)
            if cost is None:
                return Err(
                    ObservabilityError.NOT_FOUND,
                    message=f"Session {session_id} not found",
                )
            return Ok(
                {
                    "session_id": session_id,
                    "input_tokens": getattr(cost, "input_tokens", 0),
                    "output_tokens": getattr(cost, "output_tokens", 0),
                    "total_tokens": getattr(cost, "total_tokens", 0),
                    "total_cost_usd": str(getattr(cost, "total_cost_usd", 0)),
                    "cache_creation_tokens": getattr(cost, "cache_creation_tokens", 0),
                    "cache_read_tokens": getattr(cost, "cache_read_tokens", 0),
                }
            )

        if execution_id:
            cost = await manager.execution_cost.get_execution_cost(execution_id)
            if cost is None:
                return Err(
                    ObservabilityError.NOT_FOUND,
                    message=f"Execution {execution_id} not found",
                )
            return Ok(
                {
                    "execution_id": execution_id,
                    "input_tokens": getattr(cost, "input_tokens", 0),
                    "output_tokens": getattr(cost, "output_tokens", 0),
                    "total_tokens": getattr(cost, "total_tokens", 0),
                    "total_cost_usd": str(getattr(cost, "total_cost_usd", 0)),
                }
            )

        return Err(
            ObservabilityError.QUERY_FAILED,
            message="Either execution_id or session_id is required",
        )
    except Exception as e:
        return Err(ObservabilityError.QUERY_FAILED, message=str(e))


async def get_session_events(
    session_id: str,
    event_type: str | None = None,
    limit: int = 1000,
    offset: int = 0,
    auth: AuthContext | None = None,
) -> Result[list[EventRecord], ObservabilityError]:
    """Get raw events for a session from the event store.

    Args:
        session_id: The session to query.
        event_type: Optional event type filter.
        limit: Maximum events to return.
        offset: Pagination offset.
        auth: Optional authentication context.
    """
    await ensure_connected()
    try:
        store = get_event_store_instance()
        await store.initialize()
        events = await store.query(
            session_id=session_id,
            event_type=event_type,
            limit=limit,
            offset=offset,
        )
        return Ok(
            [
                EventRecord(
                    time=e.get("time"),
                    event_type=e.get("event_type", ""),
                    session_id=e.get("session_id"),
                    execution_id=e.get("execution_id"),
                    phase_id=e.get("phase_id"),
                    data=e.get("data", {}),
                )
                for e in (events or [])
            ]
        )
    except Exception as e:
        return Err(ObservabilityError.QUERY_FAILED, message=str(e))


async def get_session_timeline(
    session_id: str,
    limit: int = 1000,
    auth: AuthContext | None = None,
) -> Result[list[TimelineEntry], ObservabilityError]:
    """Get a timeline of tool operations for a session.

    Args:
        session_id: The session to query.
        limit: Maximum entries to return.
        auth: Optional authentication context.
    """
    await ensure_connected()
    try:
        manager = get_projection_mgr()
        operations = await manager.session_tools.get(session_id)

        return Ok(
            [
                TimelineEntry(
                    time=getattr(op, "timestamp", None),
                    event_type=getattr(op, "operation_type", ""),
                    tool_name=getattr(op, "tool_name", None),
                    duration_ms=getattr(op, "duration_ms", None),
                    success=getattr(op, "success", None),
                )
                for op in (operations or [])[:limit]
            ]
        )
    except Exception as e:
        return Err(ObservabilityError.QUERY_FAILED, message=str(e))


async def get_session_tool_summary(
    session_id: str,
    auth: AuthContext | None = None,
) -> Result[list[ToolUsageSummary], ObservabilityError]:
    """Get aggregated tool usage summary for a session.

    Args:
        session_id: The session to query.
        auth: Optional authentication context.
    """
    await ensure_connected()
    try:
        manager = get_projection_mgr()
        operations = await manager.session_tools.get(session_id)

        tool_stats: dict[str, dict] = {}
        for op in operations or []:
            name = getattr(op, "tool_name", None) or "unknown"
            if name not in tool_stats:
                tool_stats[name] = {
                    "call_count": 0,
                    "success_count": 0,
                    "error_count": 0,
                    "total_duration_ms": 0.0,
                }
            tool_stats[name]["call_count"] += 1
            if getattr(op, "success", None) is True:
                tool_stats[name]["success_count"] += 1
            elif getattr(op, "success", None) is False:
                tool_stats[name]["error_count"] += 1
            tool_stats[name]["total_duration_ms"] += getattr(op, "duration_ms", 0) or 0

        return Ok(
            [
                ToolUsageSummary(
                    tool_name=name,
                    call_count=stats["call_count"],
                    success_count=stats["success_count"],
                    error_count=stats["error_count"],
                    total_duration_ms=stats["total_duration_ms"],
                )
                for name, stats in tool_stats.items()
            ]
        )
    except Exception as e:
        return Err(ObservabilityError.QUERY_FAILED, message=str(e))
