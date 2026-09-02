"""Event API endpoints and service operations.

Provides session event queries, timelines, cost summaries, and tool summaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import (
    datetime,  # noqa: TC003 — Pydantic needs datetime at runtime for model validation
)
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from syn_api._wiring import ensure_connected, get_event_store_instance, get_projection_mgr
from syn_api.types import (
    Err,
    EventRecord,
    ObservabilityError,
    Ok,
    Result,
    TimelineEntry,
    ToolUsageSummary,
)

if TYPE_CHECKING:
    from syn_adapters.projections.manager import ProjectionManager
    from syn_adapters.projections.session_tools import ToolOperation as AdapterToolOperation

router = APIRouter(prefix="/events", tags=["events"])


# ============================================================================
# Response Models
# ============================================================================


class EventResponse(BaseModel):
    """Single event response."""

    time: datetime | str | None = None
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


class TimelineEntryResponse(BaseModel):
    """Timeline entry for visualization."""

    time: datetime | str | None = None
    event_type: str
    tool_name: str | None = None
    duration_ms: int | None = None
    success: bool | None = None


class CostSummaryResponse(BaseModel):
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
# Service functions (importable by tests)
# ============================================================================


async def get_session_events(
    session_id: str,
    event_type: str | None = None,
    limit: int = 1000,
    offset: int = 0,
) -> Result[list[EventRecord], ObservabilityError]:
    """Get raw events for a session from the event store.

    Args:
        session_id: The session to query.
        event_type: Optional event type filter.
        limit: Maximum events to return.
        offset: Pagination offset.
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
) -> Result[list[TimelineEntry], ObservabilityError]:
    """Get a timeline of tool operations for a session.

    Args:
        session_id: The session to query.
        limit: Maximum entries to return.
    """
    await ensure_connected()
    try:
        manager = get_projection_mgr()
        operations = await manager.session_tools.get(session_id)

        return Ok(
            [
                TimelineEntry(
                    time=op.timestamp,
                    event_type=op.operation_type,
                    tool_name=op.tool_name,
                    duration_ms=op.duration_ms,
                    success=op.success,
                )
                for op in (operations or [])[:limit]
            ]
        )
    except Exception as e:
        return Err(ObservabilityError.QUERY_FAILED, message=str(e))


@dataclass
class _CallState:
    """Tracks the single call a `tool_use_id` has already been counted under."""

    tool_name: str
    has_success: bool = False
    has_duration: bool = False


def _accumulate_tool_stats(
    operations: list[AdapterToolOperation],
) -> dict[str, dict[str, int | float]]:
    """Aggregate tool operation stats by tool name.

    `tool_execution_started` and `tool_execution_completed` are two rows for
    the same logical call, so counting every row doubles `call_count`
    (#1061). Counting only started rows undercounts instead (#1063):

    - A completion can arrive with no matching start (Codex explicitly
      supports this for a truncated stream, CodexStreamProcessor.py
      `_handle_command_execution_completed`) and the query never requires a
      pair, so that completion-only row would report `call_count=0` next to
      `success_count=1` - an impossible summary.
    - The projection rewrites an Agent/Task call's started row from
      `tool_execution_started` to `subagent_started` before it reaches here
      (session_tools_converters.py `row_to_subagent_operation`), so
      `is_started` is false for it too. Counting on `is_started` alone drops
      every subagent call to zero.

    Fix: dedupe by identity. `tool_use_id` is the identity for a real tool
    call and survives the subagent rewrite and completion-only rows. But
    `tool_use_id` is `Optional` end to end - `ToolOperation.tool_use_id`,
    the standard converter (`session_tools_dispatch.py`), and git-event rows
    (`session_tools_converters.row_to_git_operation`, which always sets it to
    `None`) all pass a missing id straight through. A prior version of this
    function fell back to per-row, `is_started`-gated counting for rows with
    no `tool_use_id`, which reintroduces the exact impossible-summary shape
    for any no-id completion row - and git rows have no `tool_use_id` by
    construction, so every git operation in every session hit it
    unconditionally (verified: a lone `git_commit` row reported
    `call_count=0, success_count=1`), not just the rarer Codex no-id case.

    The invariant this function must hold for every row shape, matched or
    not: `call_count >= success_count + error_count`. Gating call_count on
    `is_started` for the no-id case cannot satisfy that, because a
    completion can be the only row and `is_started` is always false for it.

    Chosen fix: fall back to `observation_id` as the identity when
    `tool_use_id` is absent, instead of a per-row counting rule. This is not
    a new synthetic key - `observation_id` already exists on every
    `ToolOperation` as the row's own stable identity (it's exposed to
    clients as `operation_id` in `sessions.py`/`observability.py`), and it
    is derived deterministically from row content the converters already
    have (event type, tool_use_id, timestamp, or an explicit
    `observation_id` in the event payload) - never from `uuid4()` at read
    time. That determinism is what keeps replay safe: the event store can
    deliver the same row twice, and a row replayed byte-for-byte produces
    the same `observation_id` both times, so it collapses into the same
    `_CallState` exactly like a duplicated `tool_use_id` row already did.
    An upstream repair (making the converters synthesize a real
    `tool_use_id`) was rejected here: it would duplicate the identity logic
    that `observation_id` already implements correctly, for no benefit to a
    caller of this function.

    Cost: `observation_id`'s timestamp component is only as precise as the
    stored `time` column. Two genuinely distinct no-id calls for the same
    tool that land in the same timestamp bucket would collide and be
    undercounted as one - the same accepted risk the `tool_use_id` path
    already carries for a duplicate id, now extended to the no-id path
    instead of guaranteeing an impossible summary on every such row.
    """
    tool_stats: dict[str, dict[str, int | float]] = {}
    calls: dict[str, _CallState] = {}

    def stats_for(name: str) -> dict[str, int | float]:
        return tool_stats.setdefault(
            name,
            {"call_count": 0, "success_count": 0, "error_count": 0, "total_duration_ms": 0.0},
        )

    for op in operations:
        name = op.tool_name or "unknown"
        identity = op.tool_use_id or op.observation_id

        call = calls.get(identity)
        if call is None:
            call = _CallState(tool_name=name)
            calls[identity] = call
            stats_for(name)["call_count"] += 1

        if not call.has_success and op.success is not None:
            call.has_success = True
            if op.success:
                stats_for(call.tool_name)["success_count"] += 1
            else:
                stats_for(call.tool_name)["error_count"] += 1

        if not call.has_duration and op.duration_ms is not None:
            call.has_duration = True
            stats_for(call.tool_name)["total_duration_ms"] += op.duration_ms

    return tool_stats


async def get_session_tool_summary(
    session_id: str,
) -> Result[list[ToolUsageSummary], ObservabilityError]:
    """Get aggregated tool usage summary for a session.

    Args:
        session_id: The session to query.
    """
    await ensure_connected()
    try:
        manager = get_projection_mgr()
        operations = await manager.session_tools.get(session_id)
        tool_stats = _accumulate_tool_stats(operations or [])

        return Ok(
            [
                ToolUsageSummary(
                    tool_name=name,
                    call_count=int(stats["call_count"]),
                    success_count=int(stats["success_count"]),
                    error_count=int(stats["error_count"]),
                    total_duration_ms=stats["total_duration_ms"],
                )
                for name, stats in tool_stats.items()
            ]
        )
    except Exception as e:
        return Err(ObservabilityError.QUERY_FAILED, message=str(e))


async def get_recent_activity_events(
    limit: int = 50,
    event_type: str | None = None,
) -> Result[list[dict[str, Any]], ObservabilityError]:
    """Get recent activity events for the global dashboard feed.

    When event_type is provided, filters to that single type.
    Otherwise returns all event types, ordered newest-first.

    Args:
        limit: Maximum events to return.
        event_type: Optional event type filter (e.g. "git_commit").

    Returns:
        Ok(list[dict]) on success.
    """
    await ensure_connected()
    try:
        store = get_event_store_instance()
        await store.initialize()
        events = await store.query_recent(limit=limit, event_type=event_type)
        return Ok(events)
    except Exception as e:
        return Err(ObservabilityError.QUERY_FAILED, message=str(e))


async def _get_session_token_metrics(
    manager: ProjectionManager, session_id: str
) -> Result[dict[str, Any], ObservabilityError]:
    """Build token metrics dict for a single session."""
    cost = await manager.session_cost.get_session_cost(session_id)
    if cost is None:
        return Err(ObservabilityError.NOT_FOUND, message=f"Session {session_id} not found")
    return Ok(
        {
            "session_id": session_id,
            "input_tokens": cost.input_tokens,
            "output_tokens": cost.output_tokens,
            "total_tokens": cost.total_tokens,
            "total_cost_usd": str(cost.total_cost_usd),
            "cache_creation_tokens": cost.cache_creation_tokens,
            "cache_read_tokens": cost.cache_read_tokens,
        }
    )


async def _get_execution_token_metrics(
    manager: ProjectionManager, execution_id: str
) -> Result[dict[str, Any], ObservabilityError]:
    """Build token metrics dict for a single execution."""
    exec_cost = await manager.execution_cost.get_execution_cost(execution_id)
    if exec_cost is None:
        return Err(ObservabilityError.NOT_FOUND, message=f"Execution {execution_id} not found")
    return Ok(
        {
            "execution_id": execution_id,
            "input_tokens": exec_cost.input_tokens,
            "output_tokens": exec_cost.output_tokens,
            "total_tokens": exec_cost.total_tokens,
            "total_cost_usd": str(exec_cost.total_cost_usd),
        }
    )


async def get_token_metrics(
    execution_id: str | None = None,
    session_id: str | None = None,
) -> Result[dict[str, Any], ObservabilityError]:
    """Get token usage metrics for an execution or session.

    Args:
        execution_id: Filter by execution ID.
        session_id: Filter by session ID.

    Returns:
        Ok(dict) with token metrics on success.
    """
    await ensure_connected()
    try:
        manager = get_projection_mgr()

        if session_id:
            return await _get_session_token_metrics(manager, session_id)

        if execution_id:
            return await _get_execution_token_metrics(manager, execution_id)

        return Err(
            ObservabilityError.QUERY_FAILED,
            message="Either execution_id or session_id is required",
        )
    except Exception as e:
        return Err(ObservabilityError.QUERY_FAILED, message=str(e))


# ============================================================================
# HTTP Endpoints
# ============================================================================


@router.get("/recent", response_model=EventListResponse)
async def get_recent_activity_endpoint(
    limit: int = Query(50, ge=1, le=200, description="Max events to return"),
    event_type: str | None = Query(None, description="Filter by event type"),
) -> EventListResponse:
    """Get recent activity events for the global dashboard feed."""
    result = await get_recent_activity_events(limit=limit, event_type=event_type)

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
async def get_session_events_endpoint(
    session_id: str,
    event_type: str | None = Query(None, description="Filter by event type"),
    limit: int = Query(100, ge=1, le=1000, description="Max events to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> EventListResponse:
    """Get all events for a session."""
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    session_id = await resolve_or_raise(mgr.store, "session_summaries", session_id, "Session")
    result = await get_session_events(
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


@router.get("/sessions/{session_id}/timeline", response_model=list[TimelineEntryResponse])
async def get_session_timeline_endpoint(
    session_id: str,
    limit: int = Query(100, ge=1, le=500, description="Max entries"),
) -> list[TimelineEntryResponse]:
    """Get a timeline view of session events."""
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    session_id = await resolve_or_raise(mgr.store, "session_summaries", session_id, "Session")
    result = await get_session_timeline(session_id=session_id, limit=limit)

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=f"Failed to get timeline: {result.message}")

    return [
        TimelineEntryResponse(
            time=e.time,
            event_type=e.event_type,
            tool_name=e.tool_name,
            duration_ms=int(e.duration_ms) if e.duration_ms else None,
            success=e.success,
        )
        for e in result.value
    ]


@router.get("/sessions/{session_id}/costs", response_model=CostSummaryResponse)
async def get_session_costs_endpoint(session_id: str) -> CostSummaryResponse:
    """Get cost summary for a session."""
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    session_id = await resolve_or_raise(mgr.store, "session_summaries", session_id, "Session")
    result = await get_token_metrics(session_id=session_id)

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=f"Failed to get costs: {result.message}")

    data = result.value
    return CostSummaryResponse(
        session_id=session_id,
        input_tokens=data.get("input_tokens", 0),
        output_tokens=data.get("output_tokens", 0),
        total_tokens=data.get("total_tokens", 0),
        cache_creation_tokens=data.get("cache_creation_tokens", 0),
        cache_read_tokens=data.get("cache_read_tokens", 0),
        estimated_cost_usd=float(data["total_cost_usd"]) if "total_cost_usd" in data else None,
    )


@router.get("/sessions/{session_id}/tools", response_model=list[ToolSummary])
async def get_session_tools_endpoint(session_id: str) -> list[ToolSummary]:
    """Get tool usage summary for a session."""
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    session_id = await resolve_or_raise(mgr.store, "session_summaries", session_id, "Session")
    result = await get_session_tool_summary(session_id=session_id)

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
