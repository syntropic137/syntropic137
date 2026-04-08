"""Session API endpoints and service operations.

Provides listing, starting, completing, and retrieving agent sessions.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import (
    datetime,  # noqa: TC003 — Pydantic needs datetime at runtime for model validation
)
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from syn_api._wiring import (
    ensure_connected,
    get_projection_mgr,
    get_session_cost_query,
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
from syn_domain.contexts.orchestration.slices.list_workflows.projection import (
    WorkflowListProjection,
)

if TYPE_CHECKING:
    from syn_adapters.projections.manager import ProjectionManager
    from syn_api.auth import AuthContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


# =============================================================================
# Response Models
# =============================================================================


class SessionSummaryResponse(BaseModel):
    """Summary of an agent session."""

    id: str
    workflow_id: str | None
    workflow_name: str | None = None
    execution_id: str | None = None
    phase_id: str | None
    status: str
    agent_provider: str | None
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    started_at: str | None = None
    completed_at: str | None = None


class SessionListResponse(BaseModel):
    """Wrapped list of session summaries."""

    sessions: list[SessionSummaryResponse] = Field(default_factory=list)
    total: int = 0


class OperationInfo(BaseModel):
    """Information about a session operation."""

    operation_id: str
    operation_type: str
    timestamp: datetime | str | None = None
    duration_seconds: float | None = None
    success: bool = True
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    tool_name: str | None = None
    tool_use_id: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: str | None = None
    message_role: str | None = None
    message_content: str | None = None
    thinking_content: str | None = None
    git_sha: str | None = None
    git_message: str | None = None
    git_branch: str | None = None
    git_repo: str | None = None


class SessionResponse(BaseModel):
    """Detailed session response."""

    id: str
    workflow_id: str | None
    workflow_name: str | None = None
    execution_id: str | None = None
    phase_id: str | None
    milestone_id: str | None
    agent_provider: str | None
    agent_model: str | None
    status: str
    workspace_path: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    cost_by_model: dict[str, Decimal] = Field(default_factory=dict)
    operations: list[OperationInfo] = Field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Service functions (importable by tests)
# =============================================================================


async def _fetch_one_workflow_name(
    manager: ProjectionManager, wf_id: str
) -> tuple[str, str] | None:
    """Fetch a single workflow name; returns (id, name) or None on failure."""
    try:
        wf_data = await manager.store.get(WorkflowListProjection.PROJECTION_NAME, wf_id)
        if isinstance(wf_data, dict) and wf_data.get("name"):
            return wf_id, wf_data["name"]
    except Exception:
        logger.debug("Could not load workflow name for %s", wf_id, exc_info=True)
    return None


_WF_NAME_CONCURRENCY = 20


async def _build_workflow_name_map(workflow_ids: set[str]) -> dict[str, str]:
    """Build a {workflow_id: workflow_name} lookup for the given IDs via concurrent store lookups."""
    if not workflow_ids:
        return {}
    manager = get_projection_mgr()
    semaphore = asyncio.Semaphore(_WF_NAME_CONCURRENCY)

    async def _fetch_bounded(wf_id: str) -> tuple[str, str] | None:
        async with semaphore:
            return await _fetch_one_workflow_name(manager, wf_id)

    results = await asyncio.gather(*(_fetch_bounded(wf_id) for wf_id in workflow_ids))
    return dict(entry for entry in results if entry is not None)


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


@dataclass
class _CostData:
    """Intermediate cost data extracted from projections."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    agent_model: str | None = None
    cost_by_model: dict[str, Decimal] = field(default_factory=dict)
    duration_seconds: float | None = None


async def _load_tool_operations(manager: ProjectionManager, session_id: str) -> list[ToolOperation]:
    """Load tool operations for a session from the projection."""
    try:
        tool_data = await manager.session_tools.get(session_id)
        return [ToolOperation.model_validate(op, from_attributes=True) for op in (tool_data or [])]
    except Exception:
        logger.exception("Failed to load tool operations for session %s", session_id)
        return []


async def _load_cost_data(
    session_id: str, fallback_tokens: int, fallback_cost: Decimal
) -> _CostData:
    """Load cost data for a session via SessionCostQueryService (TimescaleDB).

    Uses the query service directly instead of the deprecated projection method.
    See #532 for the architectural rationale.
    """
    try:
        query_svc = get_session_cost_query()
        cost = await query_svc.get(session_id)
    except Exception:
        logger.exception("Failed to load cost data for session %s", session_id)
        return _CostData(total_tokens=fallback_tokens, total_cost_usd=fallback_cost)

    if cost is None:
        return _CostData(total_tokens=fallback_tokens, total_cost_usd=fallback_cost)

    return _CostData(
        input_tokens=cost.input_tokens,
        output_tokens=cost.output_tokens,
        cache_creation_tokens=cost.cache_creation_tokens,
        cache_read_tokens=cost.cache_read_tokens,
        # ISS-217: Use authoritative totals from cost projection; fall back to session_list
        total_tokens=cost.total_tokens or fallback_tokens,
        total_cost_usd=cost.total_cost_usd,
        agent_model=cost.agent_model,
        cost_by_model=cost.cost_by_model,
        duration_seconds=(cost.duration_ms / 1000.0) if cost.duration_ms else None,
    )


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

    operations = await _load_tool_operations(manager, session_id)
    cd = await _load_cost_data(session_id, session.total_tokens, session.total_cost_usd)

    # Resolve workflow name with a targeted store lookup (avoids loading all workflows)
    wf_name: str | None = None
    if session.workflow_id:
        try:
            wf_data = await manager.store.get(
                WorkflowListProjection.PROJECTION_NAME, session.workflow_id
            )
            if isinstance(wf_data, dict):
                wf_name = wf_data.get("name")
        except Exception:
            logger.debug("Could not load workflow name for session %s", session_id, exc_info=True)

    return Ok(
        SessionDetail(
            id=session.id,
            workflow_id=session.workflow_id,
            workflow_name=wf_name,
            execution_id=session.execution_id,
            phase_id=session.phase_id,
            agent_type=session.agent_type,
            status=session.status,
            input_tokens=cd.input_tokens,
            output_tokens=cd.output_tokens,
            cache_creation_tokens=cd.cache_creation_tokens,
            cache_read_tokens=cd.cache_read_tokens,
            total_tokens=cd.total_tokens,
            total_cost_usd=cd.total_cost_usd,
            agent_model=cd.agent_model,
            cost_by_model=dict(cd.cost_by_model),
            operations=operations,
            started_at=session.started_at,
            completed_at=session.completed_at,
            duration_seconds=cd.duration_seconds,
            error_message=session.error_message,
        )
    )


# =============================================================================
# HTTP Endpoints
# =============================================================================


@router.get("", response_model=SessionListResponse)
async def list_sessions_endpoint(
    workflow_id: str | None = Query(None, description="Filter by workflow ID"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
) -> SessionListResponse:
    """List agent sessions with optional filtering."""
    result = await list_sessions(
        workflow_id=workflow_id,
        status=status,
        limit=limit,
    )

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    summaries = result.value
    wf_ids = {s.workflow_id for s in summaries if s.workflow_id}
    wf_names = await _build_workflow_name_map(wf_ids)
    responses = [
        SessionSummaryResponse(
            id=s.id,
            workflow_id=s.workflow_id,
            workflow_name=wf_names.get(s.workflow_id, None) if s.workflow_id else None,
            execution_id=s.execution_id,
            phase_id=s.phase_id,
            status=s.status,
            agent_provider=s.agent_type,
            total_tokens=s.total_tokens,
            total_cost_usd=s.total_cost_usd,
            started_at=str(s.started_at) if s.started_at else None,
            completed_at=str(s.completed_at) if s.completed_at else None,
        )
        for s in summaries
    ]
    return SessionListResponse(
        sessions=responses,
        total=len(responses),
    )


def _parse_tool_input(input_preview: str | None) -> dict[str, Any] | None:
    """Parse a tool input preview string into a dict."""
    if not input_preview:
        return None
    import json

    try:
        parsed = json.loads(input_preview)
        return parsed if isinstance(parsed, dict) else {"raw": input_preview}
    except (json.JSONDecodeError, TypeError):
        return {"raw": input_preview}


def _to_operation_info(op: ToolOperation) -> OperationInfo:
    """Convert a ToolOperation to an OperationInfo response model."""
    return OperationInfo(
        operation_id=op.observation_id,
        operation_type=op.operation_type,
        timestamp=str(op.timestamp) if op.timestamp else None,
        duration_seconds=(op.duration_ms / 1000.0) if op.duration_ms else None,
        success=op.success if op.success is not None else True,
        tool_name=op.tool_name,
        tool_use_id=op.tool_use_id,
        tool_input=_parse_tool_input(op.input_preview),
        tool_output=op.output_preview,
        git_sha=op.git_sha,
        git_message=op.git_message,
        git_branch=op.git_branch,
        git_repo=op.git_repo,
    )


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session_endpoint(session_id: str) -> SessionResponse:
    """Get session details by ID (supports partial ID prefix matching)."""
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    session_id = await resolve_or_raise(mgr.store, "session_summaries", session_id, "Session")
    result = await get_session(session_id)

    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    detail = result.value
    operations = [_to_operation_info(op) for op in (detail.operations or [])]

    return SessionResponse(
        id=detail.id,
        workflow_id=detail.workflow_id,
        workflow_name=detail.workflow_name,
        execution_id=detail.execution_id,
        phase_id=detail.phase_id,
        milestone_id=None,
        agent_provider=detail.agent_type,
        agent_model=detail.agent_model,
        status=detail.status,
        workspace_path=detail.workspace_path,
        input_tokens=detail.input_tokens,
        output_tokens=detail.output_tokens,
        cache_creation_tokens=detail.cache_creation_tokens,
        cache_read_tokens=detail.cache_read_tokens,
        total_tokens=detail.total_tokens,
        total_cost_usd=Decimal(str(detail.total_cost_usd)),
        cost_by_model=detail.cost_by_model,
        operations=operations,
        started_at=str(detail.started_at) if detail.started_at else None,
        completed_at=str(detail.completed_at) if detail.completed_at else None,
        duration_seconds=detail.duration_seconds,
        error_message=detail.error_message,
        metadata={},
    )
