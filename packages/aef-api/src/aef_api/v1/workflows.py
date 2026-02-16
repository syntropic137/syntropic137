"""Workflow operations — create, list, get, execute, and query executions.

Maps to the orchestration context in aef-domain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from aef_api._wiring import (
    ensure_connected,
    get_execution_engine,
    get_projection_mgr,
    get_publisher,
    get_workflow_repo,
    sync_published_events_to_projections,
)
from aef_api.types import (
    Err,
    ExecutionDetail,
    ExecutionSummary,
    Ok,
    Result,
    WorkflowDetail,
    WorkflowError,
    WorkflowSummary,
    WorkflowValidation,
)

if TYPE_CHECKING:
    from aef_api.auth import AuthContext


async def list_workflows(
    workflow_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[WorkflowSummary], WorkflowError]:
    """List all workflow templates.

    Args:
        workflow_type: Optional filter by workflow type.
        limit: Maximum results to return.
        offset: Pagination offset.
        auth: Optional authentication context.

    Returns:
        Ok(list[WorkflowSummary]) on success, Err(WorkflowError) on failure.
    """
    await ensure_connected()
    manager = get_projection_mgr()
    projection = manager.workflow_list
    domain_summaries = await projection.query(
        workflow_type_filter=workflow_type,
        limit=limit,
        offset=offset,
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
            )
            for s in domain_summaries
        ]
    )


async def get_workflow(
    workflow_id: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[WorkflowDetail, WorkflowError]:
    """Get detailed information about a workflow template.

    Args:
        workflow_id: The workflow template ID.
        auth: Optional authentication context.

    Returns:
        Ok(WorkflowDetail) on success, Err(WorkflowError.NOT_FOUND) if missing.
    """
    await ensure_connected()
    manager = get_projection_mgr()
    detail = await manager.workflow_detail.get_by_id(workflow_id)
    if detail is None:
        return Err(WorkflowError.NOT_FOUND, message=f"Workflow {workflow_id} not found")
    return Ok(
        WorkflowDetail(
            id=detail.id,
            name=detail.name,
            description=detail.description,
            workflow_type=detail.workflow_type,
            classification=detail.classification,
            phases=[],  # Phase details available via detail.phases
            created_at=detail.created_at,
            runs_count=detail.runs_count,
        )
    )


async def create_workflow(
    name: str,
    workflow_type: str = "custom",
    classification: str = "standard",
    repository_url: str = "https://github.com/example/repo",
    repository_ref: str = "main",
    description: str | None = None,
    phases: list[dict[str, Any]] | None = None,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[str, WorkflowError]:
    """Create a new workflow template.

    Args:
        name: Workflow name.
        workflow_type: Type (research, planning, implementation, review, deployment, custom).
        classification: Classification (standard, advanced).
        repository_url: Repository URL for the workflow.
        repository_ref: Repository ref/branch.
        description: Optional description.
        phases: Optional list of phase definitions. Defaults to a single initial phase.
        auth: Optional authentication context.

    Returns:
        Ok(workflow_id) on success, Err(WorkflowError) on failure.
    """
    from aef_domain.contexts.orchestration._shared.WorkflowValueObjects import (
        PhaseDefinition,
        WorkflowClassification,
        WorkflowType,
    )
    from aef_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
        CreateWorkflowTemplateCommand,
    )
    from aef_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
        CreateWorkflowTemplateHandler,
    )

    type_map: dict[str, WorkflowType] = {
        "research": WorkflowType.RESEARCH,
        "planning": WorkflowType.PLANNING,
        "implementation": WorkflowType.IMPLEMENTATION,
        "review": WorkflowType.REVIEW,
        "deployment": WorkflowType.DEPLOYMENT,
        "custom": WorkflowType.CUSTOM,
    }
    wf_type = type_map.get(workflow_type.lower(), WorkflowType.CUSTOM)

    classification_map: dict[str, WorkflowClassification] = {
        "simple": WorkflowClassification.SIMPLE,
        "standard": WorkflowClassification.STANDARD,
        "complex": WorkflowClassification.COMPLEX,
        "epic": WorkflowClassification.EPIC,
    }
    wf_classification = classification_map.get(
        classification.lower(), WorkflowClassification.STANDARD
    )

    if phases:
        phase_defs = [
            PhaseDefinition(
                phase_id=p.get("phase_id", str(uuid4())),
                name=p["name"],
                order=p.get("order", i + 1),
                description=p.get("description", ""),
            )
            for i, p in enumerate(phases)
        ]
    else:
        phase_defs = [
            PhaseDefinition(
                phase_id=str(uuid4()),
                name="Initial Phase",
                order=1,
                description="Default initial phase",
            )
        ]

    command = CreateWorkflowTemplateCommand(
        aggregate_id=str(uuid4()),
        name=name,
        description=description or f"Workflow: {name}",
        workflow_type=wf_type,
        classification=wf_classification,
        repository_url=repository_url,
        repository_ref=repository_ref,
        phases=phase_defs,
    )

    await ensure_connected()
    repository = get_workflow_repo()
    publisher = get_publisher()
    handler = CreateWorkflowTemplateHandler(
        repository=repository,
        event_publisher=publisher,
    )

    try:
        workflow_id = await handler.handle(command)
        await sync_published_events_to_projections()
        return Ok(workflow_id)
    except Exception as e:
        return Err(WorkflowError.INVALID_INPUT, message=str(e))


async def execute_workflow(
    workflow_id: str,
    inputs: dict[str, str] | None = None,
    execution_id: str | None = None,
    use_container: bool = True,  # noqa: ARG001
    tenant_id: str | None = None,  # noqa: ARG001
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[ExecutionSummary, WorkflowError]:
    """Execute a workflow.

    Args:
        workflow_id: ID of the workflow template to execute.
        inputs: Input variables for the workflow.
        execution_id: Optional execution ID (auto-generated if omitted).
        use_container: Whether to use container isolation (default True).
        tenant_id: Optional tenant ID for multi-tenant deployments.
        auth: Optional authentication context.

    Returns:
        Ok(ExecutionSummary) on success, Err(WorkflowError) on failure.
    """
    from aef_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionEngine import (
        WorkflowNotFoundError,
    )

    await ensure_connected()

    # Look up workflow name for the summary
    manager = get_projection_mgr()
    detail = await manager.workflow_detail.get_by_id(workflow_id)
    workflow_name = detail.name if detail else ""

    engine = await get_execution_engine()

    try:
        result = await engine.execute(
            workflow_id=workflow_id,
            inputs=inputs or {},
            execution_id=execution_id,
        )
    except WorkflowNotFoundError:
        return Err(WorkflowError.NOT_FOUND, message=f"Workflow {workflow_id} not found")
    except Exception as e:
        return Err(WorkflowError.EXECUTION_FAILED, message=str(e))

    return Ok(
        ExecutionSummary(
            workflow_execution_id=result.execution_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            status=result.status.value,
            completed_phases=result.metrics.completed_phases,
            total_phases=result.metrics.total_phases,
            total_tokens=result.metrics.total_tokens,
            total_cost_usd=result.metrics.total_cost_usd,
            error_message=result.error_message,
        )
    )


async def get_execution(
    execution_id: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[ExecutionDetail, WorkflowError]:
    """Get detailed information about a workflow execution.

    Args:
        execution_id: The execution ID.
        auth: Optional authentication context.

    Returns:
        Ok(ExecutionDetail) on success, Err(WorkflowError.NOT_FOUND) if missing.
    """
    await ensure_connected()
    manager = get_projection_mgr()
    detail = await manager.workflow_execution_detail.get_by_id(execution_id)
    if detail is None:
        return Err(WorkflowError.NOT_FOUND, message=f"Execution {execution_id} not found")
    return Ok(
        ExecutionDetail(
            workflow_execution_id=detail.workflow_execution_id,
            workflow_id=detail.workflow_id,
            workflow_name=detail.workflow_name,
            status=detail.status,
            started_at=detail.started_at,
            completed_at=detail.completed_at,
            total_input_tokens=detail.total_input_tokens,
            total_output_tokens=detail.total_output_tokens,
            total_cost_usd=detail.total_cost_usd,
            total_duration_seconds=detail.total_duration_seconds,
            artifact_ids=list(detail.artifact_ids),
            error_message=detail.error_message,
        )
    )


async def list_executions(
    workflow_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[list[ExecutionSummary], WorkflowError]:
    """List workflow executions.

    Args:
        workflow_id: Optional filter by workflow ID.
        status: Optional filter by execution status.
        limit: Maximum results to return.
        offset: Pagination offset.
        auth: Optional authentication context.

    Returns:
        Ok(list[ExecutionSummary]) on success, Err(WorkflowError) on failure.
    """
    await ensure_connected()
    manager = get_projection_mgr()
    projection = manager.workflow_execution_list

    if workflow_id:
        domain_summaries = await projection.get_by_workflow_id(workflow_id)
    else:
        domain_summaries = await projection.get_all(
            limit=limit,
            offset=offset,
            status_filter=status,
        )

    return Ok(
        [
            ExecutionSummary(
                workflow_execution_id=s.workflow_execution_id,
                workflow_id=s.workflow_id,
                workflow_name=s.workflow_name,
                status=s.status,
                started_at=s.started_at,
                completed_at=s.completed_at,
                completed_phases=s.completed_phases,
                total_phases=s.total_phases,
                total_tokens=s.total_tokens,
                total_cost_usd=s.total_cost_usd,
                error_message=s.error_message,
            )
            for s in domain_summaries
        ]
    )


async def validate_yaml(
    yaml_path: str,
    auth: AuthContext | None = None,  # noqa: ARG001
) -> Result[WorkflowValidation, WorkflowError]:
    """Validate a workflow YAML file.

    Args:
        yaml_path: Path to the YAML file to validate.
        auth: Optional authentication context.

    Returns:
        Ok(WorkflowValidation) on success, Err(WorkflowError) on failure.
    """
    from pathlib import Path

    from aef_domain.contexts.orchestration._shared.workflow_definition import (
        WorkflowDefinition,
        validate_workflow_yaml,
    )

    path = Path(yaml_path)
    if not path.exists():
        return Err(
            WorkflowError.NOT_FOUND,
            message=f"YAML file not found: {yaml_path}",
        )

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        return Err(WorkflowError.INVALID_INPUT, message=f"Failed to read file: {e}")

    is_valid, error_msg = validate_workflow_yaml(content)

    if is_valid:
        definition = WorkflowDefinition.from_yaml(content)
        return Ok(
            WorkflowValidation(
                valid=True,
                name=definition.name,
                workflow_type=definition.type.value
                if hasattr(definition.type, "value")
                else str(definition.type),
                phase_count=len(definition.phases),
            )
        )

    return Ok(
        WorkflowValidation(
            valid=False,
            errors=[error_msg] if error_msg else ["Unknown validation error"],
        )
    )
