"""Execution command endpoints and service functions.

Execute workflow (with background task) and execution status queries scoped
to a specific workflow.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from syn_api._wiring import (
    ensure_connected,
    get_execution_processor,
    get_projection_mgr,
    get_workflow_repo,
)
from syn_api.types import (
    Err,
    ExecutionSummary,
    Ok,
    Result,
    WorkflowError,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )

logger = logging.getLogger(__name__)


# -- Repo Access Validation ---------------------------------------------------


def _parse_repo_from_url(repo_url: str | None) -> str | None:
    """Extract owner/repo from a GitHub URL, or None if not applicable."""
    if not repo_url:
        return None
    normalized = repo_url.rstrip("/")
    if "/" not in normalized:
        return None
    parts = normalized.split("/")
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return None


def _resolve_target_repo(
    workflow: WorkflowTemplateAggregate,
    inputs: dict[str, str],
    task: str | None,
) -> str | None:
    """Resolve the target owner/repo from a workflow's repository URL.

    Merges input defaults and task into placeholders, then extracts
    owner/repo. Returns None if no repo URL, unresolved placeholders
    remain, or the URL doesn't parse to a repo name.
    """
    repo_url: str | None = workflow._repository_url
    if not repo_url:
        return None

    # Merge input declaration defaults + request inputs + task
    merged: dict[str, str] = {}
    for decl in workflow.input_declarations:
        if decl.default is not None and decl.name not in merged:
            merged[decl.name] = str(decl.default)
    merged.update(inputs)
    if task is not None:
        merged["task"] = task

    for key, value in merged.items():
        repo_url = repo_url.replace(f"{{{{{key}}}}}", value)

    # Unresolved placeholders — handler will raise later with proper error
    if "{{" in repo_url:
        return None

    return _parse_repo_from_url(repo_url)


def _build_auth_error_detail(repo_full_name: str, exc: Exception) -> str:
    """Build a user-facing error detail for GitHub App auth failures."""
    exc_message = str(exc)
    if "not installed" in exc_message.lower():
        return (
            f"GitHub App not installed on repository: {repo_full_name}. "
            "Install the GitHub App on this repository before running workflows."
        )
    return f"GitHub App authentication failed for {repo_full_name}: {exc_message}"


def _apply_repo_substitution(repos: list[str], merged: dict[str, str]) -> list[str]:
    """Substitute {{key}} patterns in each repo URL; raise ValueError if any placeholders remain."""
    resolved = []
    for repo_url in repos:
        for key, value in merged.items():
            repo_url = repo_url.replace(f"{{{{{key}}}}}", value)
        if "{{" in repo_url:
            unresolved = re.findall(r"\{\{(\w+)\}\}", repo_url)
            if not unresolved:
                raise ValueError(
                    "Malformed placeholder in repos field. "
                    "Expected {{name}} with alphanumeric/underscore characters."
                )
            raise ValueError(
                f"Unresolved placeholders in repos field: {unresolved}. "
                f"Provide them via --input {', '.join(f'{k}=<value>' for k in unresolved)}."
            )
        resolved.append(repo_url)
    return resolved


def _build_merged_inputs(
    workflow: WorkflowTemplateAggregate,
    effective_inputs: dict[str, str],
    task: str | None,
) -> dict[str, str]:
    """Merge input declaration defaults, effective inputs, and task into one dict."""
    merged: dict[str, str] = {
        decl.name: str(decl.default)
        for decl in workflow.input_declarations
        if decl.default is not None
    }
    merged.update(effective_inputs)
    if task is not None:
        merged["task"] = task
    return merged


def _get_preflight_repos(
    effective_inputs: dict[str, str],
    workflow: WorkflowTemplateAggregate,
    task: str | None,
) -> list[str]:
    """Resolve the list of repos to preflight-validate for GitHub App access."""
    repos_csv = effective_inputs.get("repos", "")
    if repos_csv:
        return [u.strip() for u in repos_csv.split(",") if u.strip()]

    # Check workflow.repos with variable substitution (mirrors ExecuteWorkflowHandler._resolve_repos).
    # Without this, unresolved {{variable}} patterns in repos silently fall through to
    # repository_url (which defaults to example/repo), producing a misleading auth error.
    if workflow.repos:
        merged = _build_merged_inputs(workflow, effective_inputs, task)
        try:
            resolved = _apply_repo_substitution(workflow.repos, merged)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if resolved:
            return resolved

    fallback = _resolve_target_repo(workflow, effective_inputs, task)
    if fallback:
        return [f"https://github.com/{fallback}"]
    return []


async def _validate_all_repos_access(repo_urls: list[str]) -> None:
    """Pre-validate that the GitHub App can access all requested repositories."""
    for url in repo_urls:
        repo_full_name = _parse_repo_from_url(url)
        if repo_full_name:
            await _validate_repo_access(repo_full_name)


async def _validate_repo_access(repo_full_name: str) -> None:
    """Pre-validate that the GitHub App can access the target repository.

    Raises HTTPException(422) if the App is not installed. Logs and
    proceeds on transient errors (network, rate limit).
    """
    from syn_shared.settings.github import GitHubAppSettings

    if not GitHubAppSettings().is_configured:
        return

    from syn_adapters.github.client import GitHubAuthError, get_github_client

    try:
        await get_github_client().get_installation_for_repo(repo_full_name)
    except GitHubAuthError as exc:
        raise HTTPException(
            status_code=422,
            detail=_build_auth_error_detail(repo_full_name, exc),
        ) from exc
    except Exception as exc:
        logger.warning("Could not pre-validate repo access for %s: %s", repo_full_name, exc)


def _merge_inputs(
    workflow: WorkflowTemplateAggregate,
    inputs: dict[str, str],
    task: str | None,
) -> dict[str, str]:
    """Merge declaration defaults, provided inputs, and task."""
    merged: dict[str, str] = {
        decl.name: str(decl.default)
        for decl in workflow.input_declarations
        if decl.default is not None
    }
    merged.update(inputs)
    if task is not None:
        merged["task"] = task
    return merged


def _check_missing_declarations(
    workflow: WorkflowTemplateAggregate,
    merged: dict[str, str],
) -> None:
    """Raise 422 if any required InputDeclaration (with no default) is absent."""
    missing = [
        decl.name
        for decl in workflow.input_declarations
        if decl.required and decl.default is None and decl.name not in merged
    ]
    if not missing:
        return
    hints = [f"--input {name}=<value>" for name in sorted(missing)]
    raise HTTPException(
        status_code=422,
        detail=(
            f"Missing required inputs: {', '.join(sorted(missing))}. "
            f"Provide them via: {', '.join(hints)}"
        ),
    )


def _check_repo_url_placeholders(
    workflow: WorkflowTemplateAggregate,
    merged: dict[str, str],
) -> None:
    """Raise 422 if workflow repository_url still contains unresolved {{placeholders}}."""
    repo_url: str | None = workflow._repository_url
    if not repo_url:
        return
    for key, value in merged.items():
        repo_url = repo_url.replace(f"{{{{{key}}}}}", value)
    if "{{" not in repo_url:
        return
    unresolved = sorted(set(re.findall(r"\{\{(\w+)\}\}", repo_url)))
    if not unresolved:
        raise HTTPException(
            status_code=422,
            detail=(
                "Repository URL contains malformed placeholders. "
                "Use the format {{name}} with alphanumeric/underscore characters."
            ),
        )
    hints = [f"--input {name}=<value>" for name in unresolved]
    raise HTTPException(
        status_code=422,
        detail=(
            f"Missing required inputs: {', '.join(unresolved)}. "
            f"Provide them via: {', '.join(hints)}"
        ),
    )


def _validate_required_inputs(
    workflow: WorkflowTemplateAggregate,
    inputs: dict[str, str],
    task: str | None,
) -> None:
    """Eagerly validate that all required inputs are satisfied.

    Checks required InputDeclarations and unresolved {{placeholder}} patterns.
    Raises HTTPException(422) with a clear message listing what's missing.
    """
    merged = _merge_inputs(workflow, inputs, task)
    _check_missing_declarations(workflow, merged)
    _check_repo_url_placeholders(workflow, merged)


router = APIRouter(prefix="/workflows", tags=["execution"])


# -- Request/Response Models --------------------------------------------------


class ExecuteWorkflowRequest(BaseModel):
    """Request to execute a workflow."""

    model_config = ConfigDict(extra="forbid")

    inputs: dict[str, str] = Field(
        default_factory=dict,
        description="Input variables for the workflow.",
    )
    task: str | None = Field(
        default=None,
        description="Primary task description -- substituted for $ARGUMENTS in phase prompts.",
    )
    repos: list[str] = Field(
        default_factory=list,
        description=(
            "GitHub URLs to pre-clone for workspace hydration (ADR-058). "
            "Overrides the workflow template's repository_url. "
            "Equivalent to passing inputs={'repos': 'url1,url2'} but type-safe."
        ),
    )
    provider: str = Field(
        default="claude",
        description=(
            "Agent provider to use. Currently ignored by execute(); "
            "sending this field has no effect."
        ),
        deprecated=True,
    )
    max_budget_usd: float | None = Field(
        default=None,
        description=(
            "Maximum budget in USD. Currently ignored by execute(); "
            "sending this field has no effect."
        ),
        deprecated=True,
    )


class ExecuteWorkflowResponse(BaseModel):
    """Response after starting workflow execution."""

    execution_id: str
    workflow_id: str
    status: str = "started"
    message: str = "Workflow execution started"


class ExecutionStatusResponse(BaseModel):
    """Response for execution status check."""

    execution_id: str
    workflow_id: str
    status: str
    current_phase: str | None = None
    completed_phases: int = 0
    total_phases: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


# -- Helpers ------------------------------------------------------------------


def _to_datetime(value: datetime | str | None) -> datetime | None:
    """Convert datetime or ISO string to datetime, handling common variants safely."""
    if value is None:
        return None
    if isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            logger.warning("Failed to parse datetime from value %r", value)
            return None
    return value


# -- Service functions --------------------------------------------------------


async def execute(
    workflow_id: str,
    inputs: dict[str, str] | None = None,
    execution_id: str | None = None,
    task: str | None = None,
    tenant_id: str | None = None,  # noqa: ARG001
) -> Result[ExecutionSummary, WorkflowError]:
    """Execute a workflow.

    Args:
        workflow_id: ID of the workflow template to execute.
        inputs: Input variables for the workflow.
        execution_id: Optional execution ID (auto-generated if omitted).
        task: Optional primary task description.
        tenant_id: Optional tenant ID for multi-tenant deployments.

    Returns:
        Ok(ExecutionSummary) on success, Err(WorkflowError) on failure.
    """
    from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
        ExecuteWorkflowCommand,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
        WorkflowNotFoundError,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
        ExecuteWorkflowHandler,
    )

    await ensure_connected()
    manager = get_projection_mgr()
    detail = await manager.workflow_detail.get_by_id(workflow_id)
    workflow_name = detail.name if detail else ""

    from syn_api._wiring import get_workflow_repo

    processor = await get_execution_processor()
    handler = ExecuteWorkflowHandler(
        processor=processor,
        workflow_repository=get_workflow_repo(),
    )

    try:
        cmd = ExecuteWorkflowCommand(
            aggregate_id=workflow_id,
            inputs=inputs or {},
            execution_id=execution_id,
            task=task,
        )
        result = await handler.handle(cmd)
    except WorkflowNotFoundError:
        return Err(WorkflowError.NOT_FOUND, message=f"Workflow {workflow_id} not found")
    except Exception as e:
        logger.exception("Workflow execution error for %s", workflow_id)
        return Err(WorkflowError.EXECUTION_FAILED, message=str(e))

    return Ok(
        ExecutionSummary(
            workflow_execution_id=result.execution_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            status=result.status,
            completed_phases=result.metrics.completed_phases,
            total_phases=result.metrics.total_phases,
            total_tokens=result.metrics.total_tokens,
            total_cost_usd=result.metrics.total_cost_usd,
            error_message=result.error_message,
        )
    )


# -- HTTP Endpoints -----------------------------------------------------------


@router.post("/{workflow_id}/execute", response_model=ExecuteWorkflowResponse)
async def execute_workflow_endpoint(
    workflow_id: str,
    request: ExecuteWorkflowRequest,
    background_tasks: BackgroundTasks,
) -> ExecuteWorkflowResponse:
    """Start workflow execution in background."""
    # Pre-validate GitHub App access before creating the execution (#598)
    await ensure_connected()
    workflow_repo = get_workflow_repo()
    workflow = await workflow_repo.get_by_id(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    # Build effective inputs — repos field takes precedence over inputs["repos"] CSV
    effective_inputs: dict[str, str] = dict(request.inputs)
    if request.repos:
        effective_inputs["repos"] = ",".join(request.repos)

    # Validate required inputs before returning 200 (#639)
    _validate_required_inputs(workflow, effective_inputs, request.task)

    # Multi-repo GitHub App preflight validation
    preflight_repos = _get_preflight_repos(effective_inputs, workflow, request.task)
    await _validate_all_repos_access(preflight_repos)

    execution_id = f"exec-{uuid4().hex[:12]}"

    async def _run() -> None:
        result = await execute(
            workflow_id=workflow_id,
            inputs=effective_inputs,
            execution_id=execution_id,
            task=request.task,
        )
        if isinstance(result, Err):
            logger.error(
                "Workflow execution failed",
                extra={
                    "execution_id": execution_id,
                    "workflow_id": workflow_id,
                    "error": result.message,
                },
            )

    background_tasks.add_task(_run)
    logger.info(
        "Started workflow execution",
        extra={
            "execution_id": execution_id,
            "workflow_id": workflow_id,
            "provider": request.provider,
        },
    )
    return ExecuteWorkflowResponse(
        execution_id=execution_id,
        workflow_id=workflow_id,
        status="started",
        message=f"Workflow execution started with provider '{request.provider}'",
    )


@router.get("/{workflow_id}/executions/{execution_id}", response_model=ExecutionStatusResponse)
async def get_execution_status_endpoint(
    workflow_id: str,
    execution_id: str,
) -> ExecutionStatusResponse:
    """Get the status of a workflow execution."""
    from syn_api.prefix_resolver import resolve_or_raise

    from .queries import get_detail

    mgr = get_projection_mgr()
    execution_id = await resolve_or_raise(
        mgr.store, "workflow_execution_details", execution_id, "Execution"
    )
    result = await get_detail(execution_id)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")

    detail = result.value
    if detail.workflow_id != workflow_id:
        raise HTTPException(
            status_code=404,
            detail=f"Execution {execution_id} not found for workflow {workflow_id}",
        )

    current_phase = None
    completed_phases = 0
    total_phases = len(detail.phases) if detail.phases else 0
    for phase in detail.phases or []:
        if phase.status == "running":
            current_phase = phase.phase_id
        if phase.status == "completed":
            completed_phases += 1

    return ExecutionStatusResponse(
        execution_id=detail.workflow_execution_id,
        workflow_id=detail.workflow_id,
        status=detail.status,
        current_phase=current_phase,
        completed_phases=completed_phases,
        total_phases=total_phases,
        started_at=str(_to_datetime(detail.started_at)) if detail.started_at else None,
        completed_at=str(_to_datetime(detail.completed_at)) if detail.completed_at else None,
        error=detail.error_message,
    )


@router.get("/executions/active")
async def list_active_executions_endpoint(
    limit: int = Query(20, ge=1, le=100),
) -> list[ExecutionStatusResponse]:
    """List all active (non-completed) executions."""
    from .queries import list_active

    result = await list_active(limit=limit)
    if isinstance(result, Err):
        return []

    return [
        ExecutionStatusResponse(
            execution_id=s.workflow_execution_id,
            workflow_id=s.workflow_id,
            status=s.status,
            current_phase=None,
            completed_phases=s.completed_phases,
            total_phases=s.total_phases,
            started_at=str(_to_datetime(s.started_at)) if s.started_at else None,
            completed_at=str(_to_datetime(s.completed_at)) if s.completed_at else None,
            error=s.error_message,
        )
        for s in result.value
    ]
