"""Workflow TEMPLATE query operations and read endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from syn_api._wiring import ensure_connected, get_projection_mgr
from syn_api.types import (
    Err,
    InputDeclarationResponse,
    Ok,
    PhaseDefinitionResponse,
    Result,
    WorkflowDetail,
    WorkflowError,
    WorkflowSummary,
)

if TYPE_CHECKING:
    from syn_api.auth import AuthContext
    from syn_domain.contexts.orchestration.domain.read_models.workflow_detail import (
        InputDeclarationDetail,
        PhaseDefinitionDetail,
    )

router = APIRouter(prefix="/workflows", tags=["workflows"])

# -- Response Models ----------------------------------------------------------


class WorkflowSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    workflow_type: str
    phase_count: int
    created_at: str | None = None
    runs_count: int = 0
    is_archived: bool = False


class InputDeclarationModel(BaseModel):
    name: str
    description: str | None = None
    required: bool = True
    default: str | None = None


class PhaseDefinition(BaseModel):
    phase_id: str
    name: str
    order: int = 0
    description: str | None = None
    agent_type: str = ""
    prompt_template: str | None = None
    timeout_seconds: int = 300
    allowed_tools: list[str] = Field(default_factory=list)
    argument_hint: str | None = None
    model: str | None = None


class WorkflowResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    workflow_type: str
    classification: str
    phases: list[PhaseDefinition] = Field(default_factory=list)
    input_declarations: list[InputDeclarationModel] = Field(default_factory=list)
    created_at: str | None = None
    runs_count: int = 0
    runs_link: str | None = None


class WorkflowListResponse(BaseModel):
    workflows: list[WorkflowSummaryResponse]
    total: int
    page: int = 1
    page_size: int = 20


class ExecutionRunSummary(BaseModel):
    workflow_execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    completed_phases: int = 0
    total_phases: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    error_message: str | None = None


class ExecutionRunListResponse(BaseModel):
    runs: list[ExecutionRunSummary]
    total: int
    workflow_id: str
    workflow_name: str


class ExecutionHistoryResponse(BaseModel):
    workflow_id: str
    workflow_name: str
    executions: list[dict] = Field(default_factory=list)  # type: ignore[type-arg]
    total_executions: int = 0


# -- Mapping helpers (single source of truth for phase/input mapping) ---------


def _map_phases(raw_phases: list[PhaseDefinitionDetail] | None) -> list[PhaseDefinitionResponse]:
    """Map domain PhaseDefinitionDetail objects to API response models."""
    return [
        PhaseDefinitionResponse(
            phase_id=p.id,
            name=p.name,
            order=p.order,
            description=p.description,
            agent_type=p.agent_type,
            prompt_template=p.prompt_template,
            timeout_seconds=p.timeout_seconds or 300,
            allowed_tools=list(p.allowed_tools),
            argument_hint=p.argument_hint,
            model=p.model,
        )
        for p in (raw_phases or [])
    ]


def _map_input_declarations(
    raw_decls: list[InputDeclarationDetail] | None,
) -> list[InputDeclarationResponse]:
    """Map domain InputDeclarationDetail objects to API response models."""
    return [
        InputDeclarationResponse(
            name=d.name,
            description=d.description,
            required=d.required,
            default=d.default,
        )
        for d in (raw_decls or [])
    ]


# -- Service functions (importable by tests) ----------------------------------


async def list_workflows(
    workflow_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    include_archived: bool = False,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[WorkflowSummary], WorkflowError]:
    """List all workflow templates."""
    await ensure_connected()
    domain_summaries = await get_projection_mgr().workflow_list.query(
        workflow_type_filter=workflow_type,
        limit=limit,
        offset=offset,
        include_archived=include_archived,
    )
    return Ok(
        [
            WorkflowSummary(
                id=s.id,
                name=s.name,
                workflow_type=s.workflow_type,
                classification=s.classification,
                phase_count=s.phase_count,
                description=s.description,
                created_at=s.created_at,
                runs_count=s.runs_count,
                is_archived=s.is_archived,
            )
            for s in domain_summaries
        ]
    )


async def get_workflow(
    workflow_id: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[WorkflowDetail, WorkflowError]:
    """Get detailed workflow template with fully-mapped phase/input objects."""
    await ensure_connected()
    detail = await get_projection_mgr().workflow_detail.get_by_id(workflow_id)
    if detail is None:
        return Err(WorkflowError.NOT_FOUND, message=f"Workflow {workflow_id} not found")

    return Ok(
        WorkflowDetail(
            id=detail.id,
            name=detail.name,
            description=detail.description,
            workflow_type=detail.workflow_type,
            classification=detail.classification,
            phases=_map_phases(detail.phases),
            input_declarations=_map_input_declarations(detail.input_declarations),
            created_at=detail.created_at,
            runs_count=detail.runs_count,
        )
    )


# -- HTTP Endpoints -----------------------------------------------------------


@router.get("", response_model=WorkflowListResponse)
async def list_workflows_endpoint(
    workflow_type: str | None = Query(None, description="Filter by workflow type"),
    include_archived: bool = Query(False, description="Include archived workflows"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    order_by: str | None = Query(None, description="Sort field (- prefix = descending)"),
) -> WorkflowListResponse:
    """List all workflow templates."""
    offset = (page - 1) * page_size
    result = await list_workflows(
        workflow_type=workflow_type,
        limit=page_size,
        offset=offset,
        include_archived=include_archived,
    )
    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    summaries = [
        WorkflowSummaryResponse(
            id=s.id,
            name=s.name,
            workflow_type=s.workflow_type,
            phase_count=s.phase_count,
            created_at=str(s.created_at) if s.created_at else None,
            runs_count=s.runs_count,
            is_archived=s.is_archived,
        )
        for s in result.value
    ]

    if order_by:
        desc, field = order_by.startswith("-"), order_by.lstrip("-")
        valid_fields = {"runs_count", "name", "workflow_type", "phase_count", "created_at"}
        if field in valid_fields:
            summaries.sort(key=lambda s: getattr(s, field) or 0, reverse=desc)

    total = len(summaries)
    return WorkflowListResponse(
        workflows=summaries[offset : offset + page_size],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow_endpoint(workflow_id: str) -> WorkflowResponse:
    """Get workflow details by ID."""
    result = await get_workflow(workflow_id)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    detail = result.value
    return WorkflowResponse(
        id=detail.id,
        name=detail.name,
        description=detail.description,
        workflow_type=detail.workflow_type,
        classification=detail.classification,
        phases=[
            PhaseDefinition(
                phase_id=p.phase_id,
                name=p.name,
                order=p.order,
                description=p.description,
                agent_type=p.agent_type,
                prompt_template=p.prompt_template,
                timeout_seconds=p.timeout_seconds,
                allowed_tools=list(p.allowed_tools),
                argument_hint=p.argument_hint,
                model=p.model,
            )
            for p in detail.phases
        ],
        input_declarations=[
            InputDeclarationModel(
                name=d.name,
                description=d.description,
                required=d.required,
                default=d.default,
            )
            for d in detail.input_declarations
        ],
        created_at=str(detail.created_at) if detail.created_at else None,
        runs_count=detail.runs_count,
        runs_link=f"/api/workflows/{detail.id}/runs",
    )


@router.get("/{workflow_id}/runs", response_model=ExecutionRunListResponse)
async def list_workflow_runs_endpoint(workflow_id: str) -> ExecutionRunListResponse:
    """List all execution runs for a workflow."""
    from syn_api.routes.executions.queries import list_ as ex_list_

    wf_result = await get_workflow(workflow_id)
    if isinstance(wf_result, Err):
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    workflow_name = wf_result.value.name
    exec_result = await ex_list_(workflow_id=workflow_id)
    if isinstance(exec_result, Err):
        raise HTTPException(status_code=500, detail=exec_result.message)

    return ExecutionRunListResponse(
        runs=[
            ExecutionRunSummary(
                workflow_execution_id=e.workflow_execution_id,
                workflow_id=e.workflow_id,
                workflow_name=e.workflow_name or workflow_name,
                status=e.status,
                started_at=str(e.started_at) if e.started_at else None,
                completed_at=str(e.completed_at) if e.completed_at else None,
                completed_phases=e.completed_phases,
                total_phases=e.total_phases,
                total_tokens=e.total_tokens,
                total_cost_usd=Decimal(str(e.total_cost_usd)),
                error_message=e.error_message,
            )
            for e in exec_result.value
        ],
        total=len(exec_result.value),
        workflow_id=workflow_id,
        workflow_name=workflow_name,
    )


@router.get("/{workflow_id}/history", response_model=ExecutionHistoryResponse)
async def get_workflow_history_endpoint(workflow_id: str) -> ExecutionHistoryResponse:
    """DEPRECATED: Use /workflows/{workflow_id}/runs instead."""
    wf_result = await get_workflow(workflow_id)
    if isinstance(wf_result, Err):
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    return ExecutionHistoryResponse(
        workflow_id=workflow_id,
        workflow_name=wf_result.value.name,
        executions=[],
        total_executions=0,
    )
