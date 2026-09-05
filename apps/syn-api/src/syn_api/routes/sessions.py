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
from syn_api.list_query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    WindowBound,
    parse_statuses,
    resolve_page_size,
)
from syn_api.types import (
    Err,
    GitEventData,
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
from syn_domain.pagination import Page
from syn_shared.display import (
    EM_DASH,
    compute_duration_seconds,
    format_cost,
    format_duration_seconds,
    format_model_compact,
    format_phase,
    format_repos,
    format_tokens,
)

if TYPE_CHECKING:
    from syn_adapters.projections.manager import ProjectionManager
    from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import (
        SessionCost,
    )
    from syn_domain.contexts.agent_sessions.domain.read_models.session_summary import (
        SessionSummary as DomainSessionSummary,
    )

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


# =============================================================================
# Response Models
# =============================================================================


class SessionSummaryResponse(BaseModel):
    """Summary of an agent session.

    Display fields (``*_display``) are produced server-side so all clients
    (dashboard, CLI, future UIs) share identical human-readable output. Raw
    fields remain for programmatic consumers; both are always present.

    Timestamps stay ISO 8601 UTC. Locale and relative-time formatting is the
    client's job (it knows the viewer's time zone and when the response is
    actually rendered).

    See: docs/adrs/ADR-064-observability-monitor-ui.md
    """

    id: str
    workflow_id: str | None
    workflow_name: str | None = None
    execution_id: str | None = None
    phase_id: str | None
    #: The session that delegated to this one, when it is a delegate (#895).
    #: None for a leader - a leader genuinely has no parent, and defaulting
    #: this to the session's own id would make the chain unwalkable rather
    #: than terminating it.
    parent_session_id: str | None = None
    #: The top of the delegation chain. Equals ``id`` for a leader.
    root_session_id: str | None = None
    phase_display: str | None = None
    status: str
    agent_provider: str | None
    agent_model: str | None = None
    agent_model_display: str | None = None
    repos: list[str] = Field(default_factory=list)
    repos_display: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    total_tokens_display: str = "0"
    total_cost_usd: Decimal = Decimal("0")
    total_cost_display: str = EM_DASH
    unpriced_observation_count: int = 0
    """Observations that carried no usable rate and so added nothing to the total.

    Non-zero means ``total_cost_usd`` is INCOMPLETE, not that the work was
    free. Clients render "unpriced" (or ">=$X (partial)") off this field rather
    than printing a dollar figure they cannot back up (issue #890).
    """
    duration_seconds: float | None = None
    duration_display: str = "\u2014"
    started_at: str | None = None
    completed_at: str | None = None


class SessionListResponse(BaseModel):
    """Wrapped list of session summaries."""

    sessions: list[SessionSummaryResponse] = Field(default_factory=list)
    total: int = 0
    """Sessions matching every filter, not the length of this page.

    This used to be ``len(sessions)``, which made it unusable for paging - it
    always said "you have them all". Nothing rendered it, so nothing broke;
    now that the endpoint pages, it is the number a client pages against.
    """
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    excluded_undated: int = 0
    """Sessions dropped from this window because they carry no date at all.

    ``total`` cannot say why a row is missing: "older than the bound" and
    "undated" leave it looking identical, so narrowing a window showed an
    unexplained gap (#1215). With this the reader gets "755 of 1037, 274
    undated" instead.

    Zero when the request gave no window - an unbounded query evaluates every
    row and returns the undated ones. Non-zero means rows exist that this
    filter could not judge, NOT that they failed it.
    """
    status_counts: dict[str, int] = Field(default_factory=dict)
    """Matching sessions tallied by status, ignoring the status filter itself."""


class OperationInfo(BaseModel):
    """Information about a session operation."""

    operation_id: str
    operation_type: str
    timestamp: datetime | str | None = None
    duration_seconds: float | None = None
    success: bool = True
    """See `PhaseOperationInfo.success` - same field, same rule, other endpoint."""
    error_message: str | None = None
    """Why this operation's subject went wrong, when something did (#1196)."""
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
    # Structured git data (v2 events - preferred)
    git: GitEventData | None = None
    # Flat git fields (deprecated - use git sub-object instead)
    git_sha: str | None = None
    git_message: str | None = None
    git_branch: str | None = None
    git_repo: str | None = None


class SessionResponse(BaseModel):
    """Detailed session response.

    Display fields (``*_display``) are produced server-side so all clients
    share identical human-readable output. Raw fields remain for programmatic
    consumers.

    See: docs/adrs/ADR-064-observability-monitor-ui.md
    """

    id: str
    workflow_id: str | None
    workflow_name: str | None = None
    execution_id: str | None = None
    phase_id: str | None
    #: The session that delegated to this one, when it is a delegate (#895).
    #: None for a leader - a leader genuinely has no parent, and defaulting
    #: this to the session's own id would make the chain unwalkable rather
    #: than terminating it.
    parent_session_id: str | None = None
    #: The top of the delegation chain. Equals ``id`` for a leader.
    root_session_id: str | None = None
    phase_display: str | None = None
    milestone_id: str | None
    agent_provider: str | None
    agent_model: str | None
    agent_model_display: str | None = None
    repos: list[str] = Field(default_factory=list)
    repos_display: str | None = None
    status: str
    workspace_path: str | None = None
    input_tokens: int = 0
    input_tokens_display: str = "0"
    output_tokens: int = 0
    output_tokens_display: str = "0"
    cache_creation_tokens: int = 0
    cache_creation_tokens_display: str = "0"
    cache_read_tokens: int = 0
    cache_read_tokens_display: str = "0"
    total_tokens: int = 0
    total_tokens_display: str = "0"
    total_cost_usd: Decimal = Decimal("0")
    total_cost_display: str = EM_DASH
    unpriced_observation_count: int = 0
    """Observations that carried no usable rate and so added nothing to the total.

    Non-zero means ``total_cost_usd`` is INCOMPLETE, not that the work was
    free. Clients render "unpriced" (or ">=$X (partial)") off this field rather
    than printing a dollar figure they cannot back up (issue #890).
    """
    cost_by_model: dict[str, Decimal] = Field(default_factory=dict)
    operations: list[OperationInfo] = Field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    duration_display: str = "\u2014"
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


@dataclass
class _SummaryEnrichment:
    """Per-session enrichment loaded from Lane 2 (cost projection).

    Lane 2 updates token + cost totals continuously as the agent runs, so
    these values are live for in-flight sessions. The domain projection
    (Lane 1) only sees final tokens on `SessionCompleted`.
    """

    total_cost_usd: Decimal = Decimal("0")
    unpriced_observation_count: int = 0
    """Observations Lane 2 could not price; non-zero means the cost is partial."""
    agent_model: str | None = None
    duration_seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cache_read_tokens: int | None = None
    total_tokens: int | None = None


def _enrichment_from_cost(cost: SessionCost) -> _SummaryEnrichment:
    """Build enrichment from a session_cost projection record."""
    duration_ms = cost.duration_ms
    return _SummaryEnrichment(
        total_cost_usd=cost.total_cost_usd,
        unpriced_observation_count=cost.unpriced_observation_count,
        agent_model=cost.agent_model,
        duration_seconds=(duration_ms / 1000.0) if duration_ms else None,
        input_tokens=cost.input_tokens,
        output_tokens=cost.output_tokens,
        cache_creation_tokens=cost.cache_creation_tokens,
        cache_read_tokens=cost.cache_read_tokens,
        total_tokens=cost.total_tokens,
    )


async def _load_session_costs(session_ids: list[str]) -> dict[str, _SummaryEnrichment]:
    """Load per-session enrichment from the Lane 2 session_cost projection (#695).

    Returns cost, agent model, and duration so the list endpoint can populate
    display fields without a second round-trip.

    ONE batched query, not one per session (#1114). The per-session loop this
    replaced cost ~41ms per row against a database that answers a whole page in
    2ms: `limit=200` took 8.3s, and the endpoint's own default of 50 took 2.4s.
    A failure still degrades to "no enrichment" rather than a 500 - the same
    behaviour the per-session version had, now decided once for the page.
    """
    if not session_ids:
        return {}
    try:
        query_svc = get_session_cost_query()
        costs = await query_svc.get_many(session_ids)
    except Exception:
        logger.debug("Session cost enrichment unavailable", exc_info=True)
        return {}
    return {sid: _enrichment_from_cost(cost) for sid, cost in costs.items()}


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


def _to_session_summary(s: DomainSessionSummary) -> SessionSummary:
    """Convert a domain read-model row into the API-layer summary."""
    return SessionSummary(
        id=s.id,
        workflow_id=s.workflow_id,
        execution_id=s.execution_id,
        phase_id=s.phase_id,
        # #895: the domain read model carries these; this conversion used to
        # drop them, so delegation lineage died at the API boundary even once
        # something wrote it.
        parent_session_id=s.parent_session_id,
        root_session_id=s.root_session_id,
        status=s.status,
        agent_type=s.agent_type,
        repos=list(s.repos),
        input_tokens=s.input_tokens,
        output_tokens=s.output_tokens,
        cache_creation_tokens=s.cache_creation_tokens,
        cache_read_tokens=s.cache_read_tokens,
        total_tokens=s.total_tokens,
        # Lane 2: cost is enriched from session_cost projection at the endpoint (#695)
        total_cost_usd=Decimal("0"),
        started_at=s.started_at,
        completed_at=s.completed_at,
    )


async def list_sessions(
    workflow_id: str | None = None,
    status: str | None = None,
    statuses: list[str] | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
    search: str | None = None,
) -> Result[Page[SessionSummary], SessionError]:
    """List agent sessions, optionally filtered.

    Returns a ``Page`` rather than a bare list because the endpoint needs the
    total and the status facets counted over the same predicate that produced
    the rows. Deriving them separately is how a count comes to describe rows
    the query does not return (#1119).

    Args:
        workflow_id: Filter by workflow ID.
        status: Filter by single session status (legacy).
        statuses: Filter by multiple statuses (OR'd together). Takes
            precedence over ``status``.
        started_after: Inclusive lower bound on ``started_at``.
        started_before: Inclusive upper bound on ``started_at``.
        limit: Maximum results to return.
        offset: Pagination offset.
        search: Case-insensitive substring match on session id or workflow id.

    Returns:
        Ok(Page[SessionSummary]) on success, Err(SessionError) on failure.
    """
    await ensure_connected()
    manager = get_projection_mgr()
    projection = manager.session_list
    domain_page = await projection.page(
        workflow_id=workflow_id,
        statuses=statuses if statuses else ([status] if status else None),
        started_after=started_after,
        started_before=started_before,
        search=search,
        limit=limit,
        offset=offset,
    )
    return Ok(
        Page(
            rows=[_to_session_summary(s) for s in domain_page.rows],
            total=domain_page.total,
            status_counts=domain_page.status_counts,
            excluded_undated=domain_page.excluded_undated,
        )
    )


async def start_session(
    workflow_id: str,
    phase_id: str | None = None,
    execution_id: str | None = None,
    agent_type: str = "claude",
) -> Result[str, SessionError]:
    """Start a new agent session.

    Args:
        workflow_id: The workflow this session belongs to.
        phase_id: Optional phase within the workflow.
        execution_id: Optional execution ID.
        agent_type: The agent provider (default: claude).

    Returns:
        Ok(session_id) on success, Err(SessionError) on failure.
    """
    from syn_domain.contexts.agent_sessions import StartSessionCommand, StartSessionHandler

    await ensure_connected()
    repository = get_session_repo()
    handler = StartSessionHandler(repository=repository)

    try:
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
) -> Result[None, SessionError]:
    """Complete an agent session.

    Args:
        session_id: The session to complete.

    Returns:
        Ok(None) on success, Err(SessionError) on failure.
    """
    from syn_domain.contexts.agent_sessions import CompleteSessionCommand, CompleteSessionHandler

    await ensure_connected()
    repository = get_session_repo()
    handler = CompleteSessionHandler(repository=repository)

    try:
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
    unpriced_observation_count: int = 0
    """Observations Lane 2 could not price; non-zero means the cost is partial."""
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
        # Dropping this was the fix failing inside its own PR: session detail is
        # the most-viewed cost surface, and without the count it renders a
        # confident dollar figure for work nobody could price (#890).
        unpriced_observation_count=cost.unpriced_observation_count,
        agent_model=cost.agent_model,
        cost_by_model=cost.cost_by_model,
        duration_seconds=(cost.duration_ms / 1000.0) if cost.duration_ms else None,
    )


async def get_session(
    session_id: str,
) -> Result[SessionDetail, SessionError]:
    """Get detailed information about a session, including tool operations and costs.

    Args:
        session_id: The session ID to look up.

    Returns:
        Ok(SessionDetail) on success, Err(SessionError.NOT_FOUND) if missing.
    """
    await ensure_connected()
    manager = get_projection_mgr()

    # Look up session in the session_list projection. This read 10000 sessions
    # and scanned them for one id, so the detail page went 404 past that row
    # (#1204, same shape as the artifact one).
    session = await manager.session_list.get_by_id(session_id)

    if session is None:
        return Err(SessionError.NOT_FOUND, message=f"Session {session_id} not found")

    operations = await _load_tool_operations(manager, session_id)
    # Lane 2: session cost from TimescaleDB; fallback to 0 if unavailable (#695)
    cd = await _load_cost_data(session_id, session.total_tokens, Decimal("0"))
    # A running session has no completed_at, so Lane 2's duration_ms is unset
    # and this reported None for the whole run. Computed against the wall clock
    # instead. Terminal sessions keep whatever Lane 2 recorded.
    duration_seconds = (
        compute_duration_seconds(session.started_at)
        if session.status == "running"
        else cd.duration_seconds
    )

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
            parent_session_id=session.parent_session_id,
            root_session_id=session.root_session_id,
            agent_type=session.agent_type,
            status=session.status,
            repos=list(session.repos),
            input_tokens=cd.input_tokens,
            output_tokens=cd.output_tokens,
            cache_creation_tokens=cd.cache_creation_tokens,
            cache_read_tokens=cd.cache_read_tokens,
            total_tokens=cd.total_tokens,
            total_cost_usd=cd.total_cost_usd,
            unpriced_observation_count=cd.unpriced_observation_count,
            agent_model=cd.agent_model,
            cost_by_model=dict(cd.cost_by_model),
            operations=operations,
            started_at=session.started_at,
            completed_at=session.completed_at,
            duration_seconds=duration_seconds,
            error_message=session.error_message,
        )
    )


# =============================================================================
# HTTP Endpoints
# =============================================================================


def _build_session_summary_response(
    s: SessionSummary,
    workflow_name: str | None,
    info: _SummaryEnrichment,
) -> SessionSummaryResponse:
    """Compose a SessionSummaryResponse from a domain summary + enrichment.

    Token + cost totals prefer Lane 2 (live) over the domain projection,
    which only finalizes on `SessionCompleted`.
    """
    input_tokens = info.input_tokens if info.input_tokens is not None else s.input_tokens
    output_tokens = info.output_tokens if info.output_tokens is not None else s.output_tokens
    cache_creation_tokens = (
        info.cache_creation_tokens
        if info.cache_creation_tokens is not None
        else s.cache_creation_tokens
    )
    cache_read_tokens = (
        info.cache_read_tokens if info.cache_read_tokens is not None else s.cache_read_tokens
    )
    total_tokens = info.total_tokens if info.total_tokens is not None else s.total_tokens
    # Same rule as get_session above. Applied here too because the LIST and the
    # DETAIL of one running session previously disagreed with each other.
    duration_seconds = (
        compute_duration_seconds(s.started_at) if s.status == "running" else info.duration_seconds
    )
    return SessionSummaryResponse(
        id=s.id,
        workflow_id=s.workflow_id,
        workflow_name=workflow_name,
        execution_id=s.execution_id,
        phase_id=s.phase_id,
        parent_session_id=s.parent_session_id,
        root_session_id=s.root_session_id,
        phase_display=format_phase(s.phase_id),
        status=s.status,
        agent_provider=s.agent_type,
        agent_model=info.agent_model,
        agent_model_display=format_model_compact(info.agent_model),
        repos=list(s.repos),
        repos_display=format_repos(s.repos),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        total_tokens=total_tokens,
        total_tokens_display=format_tokens(total_tokens),
        total_cost_usd=info.total_cost_usd,
        total_cost_display=format_cost(info.total_cost_usd, info.unpriced_observation_count),
        unpriced_observation_count=info.unpriced_observation_count,
        duration_seconds=duration_seconds,
        duration_display=format_duration_seconds(duration_seconds),
        started_at=str(s.started_at) if s.started_at else None,
        completed_at=str(s.completed_at) if s.completed_at else None,
    )


@router.get("", response_model=SessionListResponse)
async def list_sessions_endpoint(
    workflow_id: str | None = Query(None, description="Filter by workflow ID"),
    status: str | None = Query(None, description="Filter by single status (legacy)"),
    statuses: str | None = Query(
        None,
        description="Comma-separated list of statuses (OR'd; takes precedence over `status`)",
    ),
    started_after: WindowBound | None = Query(
        None, description="Inclusive ISO 8601 lower bound on started_at (timezone required)"
    ),
    started_before: WindowBound | None = Query(
        None, description="Inclusive ISO 8601 upper bound on started_at (timezone required)"
    ),
    q: str | None = Query(
        None,
        description="Case-insensitive substring match against session id and workflow id",
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int | None = Query(None, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
    limit: int | None = Query(
        None,
        ge=1,
        le=MAX_PAGE_SIZE,
        deprecated=True,
        description="Deprecated alias for page_size. Ignored when page_size is given.",
    ),
) -> SessionListResponse:
    """List agent sessions with optional filtering."""
    effective_page_size = resolve_page_size(page_size, limit)
    result = await list_sessions(
        workflow_id=workflow_id,
        status=status,
        statuses=parse_statuses(statuses, status),
        started_after=started_after,
        started_before=started_before,
        search=q,
        limit=effective_page_size,
        offset=(page - 1) * effective_page_size,
    )

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    session_page = result.value
    summaries = session_page.rows
    wf_ids = {s.workflow_id for s in summaries if s.workflow_id}
    wf_names = await _build_workflow_name_map(wf_ids)
    # Lane 2: enrich each session's cost/model/duration from the session_cost projection (#695)
    enrichment = await _load_session_costs([s.id for s in summaries])
    responses = [
        _build_session_summary_response(
            s,
            wf_names.get(s.workflow_id) if s.workflow_id else None,
            enrichment.get(s.id, _SummaryEnrichment()),
        )
        for s in summaries
    ]
    return SessionListResponse(
        sessions=responses,
        # The filtered COLLECTION, not this page. It was ``len(responses)``,
        # which said "you have them all" however much history was unreachable.
        total=session_page.total,
        page=page,
        page_size=effective_page_size,
        excluded_undated=session_page.excluded_undated,
        status_counts=session_page.status_counts,
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
        # See `_map_phase_to_response` for why None still renders as True.
        success=op.success if op.success is not None else True,
        error_message=op.error_message,
        tool_name=op.tool_name,
        tool_use_id=op.tool_use_id,
        tool_input=_parse_tool_input(op.input_preview),
        tool_output=op.output_preview,
        git=op.git,
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

    total_cost = Decimal(str(detail.total_cost_usd))
    return SessionResponse(
        id=detail.id,
        workflow_id=detail.workflow_id,
        workflow_name=detail.workflow_name,
        execution_id=detail.execution_id,
        phase_id=detail.phase_id,
        parent_session_id=detail.parent_session_id,
        root_session_id=detail.root_session_id,
        phase_display=format_phase(detail.phase_id),
        milestone_id=None,
        agent_provider=detail.agent_type,
        agent_model=detail.agent_model,
        agent_model_display=format_model_compact(detail.agent_model),
        repos=list(detail.repos),
        repos_display=format_repos(detail.repos),
        status=detail.status,
        workspace_path=detail.workspace_path,
        input_tokens=detail.input_tokens,
        input_tokens_display=format_tokens(detail.input_tokens),
        output_tokens=detail.output_tokens,
        output_tokens_display=format_tokens(detail.output_tokens),
        cache_creation_tokens=detail.cache_creation_tokens,
        cache_creation_tokens_display=format_tokens(detail.cache_creation_tokens),
        cache_read_tokens=detail.cache_read_tokens,
        cache_read_tokens_display=format_tokens(detail.cache_read_tokens),
        total_tokens=detail.total_tokens,
        total_tokens_display=format_tokens(detail.total_tokens),
        total_cost_usd=total_cost,
        total_cost_display=format_cost(total_cost, detail.unpriced_observation_count),
        unpriced_observation_count=detail.unpriced_observation_count,
        cost_by_model=detail.cost_by_model,
        operations=operations,
        started_at=str(detail.started_at) if detail.started_at else None,
        completed_at=str(detail.completed_at) if detail.completed_at else None,
        duration_seconds=detail.duration_seconds,
        duration_display=format_duration_seconds(detail.duration_seconds),
        error_message=detail.error_message,
        metadata={},
    )
