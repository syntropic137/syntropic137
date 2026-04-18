"""Workflow TEMPLATE command operations (create, validate).

Service functions are plain ``async def`` (importable by tests).
HTTP endpoints wire the service functions to ``@router.post()`` routes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from syn_api._wiring import (
    ensure_connected,
    get_projection_mgr,
    get_publisher,
    get_workflow_repo,
    sync_published_events_to_projections,
)
from syn_api.types import (
    Err,
    Ok,
    Result,
    WorkflowError,
    WorkflowValidation,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        InputDeclaration,
        PhaseDefinition,
        WorkflowClassification,
        WorkflowType,
    )

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _resolve_workflow_type(workflow_type: str) -> WorkflowType:
    from syn_domain.contexts.orchestration import WorkflowType

    type_map: dict[str, WorkflowType] = {
        "research": WorkflowType.RESEARCH,
        "planning": WorkflowType.PLANNING,
        "implementation": WorkflowType.IMPLEMENTATION,
        "review": WorkflowType.REVIEW,
        "deployment": WorkflowType.DEPLOYMENT,
        "custom": WorkflowType.CUSTOM,
    }
    return type_map.get(workflow_type.lower(), WorkflowType.CUSTOM)


def _resolve_classification(classification: str) -> WorkflowClassification:
    from syn_domain.contexts.orchestration import WorkflowClassification

    classification_map: dict[str, WorkflowClassification] = {
        "simple": WorkflowClassification.SIMPLE,
        "standard": WorkflowClassification.STANDARD,
        "complex": WorkflowClassification.COMPLEX,
        "epic": WorkflowClassification.EPIC,
    }
    return classification_map.get(classification.lower(), WorkflowClassification.STANDARD)


def _build_phase_defs(phases: list[dict[str, Any]] | None) -> list[PhaseDefinition]:
    from syn_domain.contexts.orchestration import PhaseDefinition, PhaseExecutionType

    if phases:
        return [
            PhaseDefinition(
                phase_id=p.get("phase_id", str(uuid4())),
                name=p["name"],
                order=p.get("order", i + 1),
                description=p.get("description"),
                execution_type=p.get("execution_type", PhaseExecutionType.SEQUENTIAL),
                input_artifact_types=p.get("input_artifact_types", []),
                output_artifact_types=p.get("output_artifact_types", []),
                prompt_template=p.get("prompt_template"),
                max_tokens=p.get("max_tokens"),
                timeout_seconds=p.get("timeout_seconds"),
                allowed_tools=p.get("allowed_tools", []),
                argument_hint=p.get("argument_hint"),
                model=p.get("model"),
            )
            for i, p in enumerate(phases)
        ]
    return [
        PhaseDefinition(
            phase_id=str(uuid4()),
            name="Initial Phase",
            order=1,
            description="Default initial phase",
        )
    ]


def _build_input_declarations(
    inputs: list[dict[str, Any]] | None,
) -> list[InputDeclaration]:
    from syn_domain.contexts.orchestration import InputDeclaration

    if not inputs:
        return []
    return [
        InputDeclaration(
            name=inp["name"],
            description=inp.get("description"),
            required=inp.get("required", True),
            default=inp.get("default"),
        )
        for inp in inputs
    ]


async def create_workflow(
    name: str,
    workflow_type: str = "custom",
    classification: str = "standard",
    repository_url: str = "",
    repository_ref: str = "main",
    description: str | None = None,
    project_name: str | None = None,
    phases: list[dict[str, Any]] | None = None,
    input_declarations: list[dict[str, Any]] | None = None,
    workflow_id: str | None = None,
    repos: list[str] | None = None,
    requires_repos: bool = True,
) -> Result[str, WorkflowError]:
    """Create a new workflow template.

    Args:
        name: Workflow name.
        workflow_type: Type (research, planning, implementation, review, deployment, custom).
        classification: Classification (standard, advanced).
        repository_url: Repository URL for the workflow.
        repository_ref: Repository ref/branch.
        description: Optional description.
        project_name: Optional project name association.
        phases: Optional list of phase definitions. Defaults to a single initial phase.
        input_declarations: Optional list of input declarations.
        workflow_id: Optional client-supplied ID. Auto-generated if omitted.

    Returns:
        Ok(workflow_id) on success, Err(WorkflowError) on failure.
    """
    from syn_domain.contexts.orchestration import (
        CreateWorkflowTemplateCommand,
        CreateWorkflowTemplateHandler,
    )

    command = CreateWorkflowTemplateCommand(
        aggregate_id=workflow_id or str(uuid4()),
        name=name,
        description=description or f"Workflow: {name}",
        workflow_type=_resolve_workflow_type(workflow_type),
        classification=_resolve_classification(classification),
        repository_url=repository_url,
        repository_ref=repository_ref,
        phases=_build_phase_defs(phases),
        project_name=project_name,
        input_declarations=_build_input_declarations(input_declarations),
        repos=repos or [],
        requires_repos=requires_repos,
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


async def validate_yaml(
    yaml_content: str,
) -> Result[WorkflowValidation, WorkflowError]:
    """Validate workflow YAML content.

    Args:
        yaml_content: Raw YAML content to validate.

    Returns:
        Ok(WorkflowValidation) on success, Err(WorkflowError) on failure.
    """
    from syn_domain.contexts.orchestration import WorkflowDefinition, validate_workflow_yaml

    is_valid, error_msg = validate_workflow_yaml(yaml_content)

    if is_valid:
        definition = WorkflowDefinition.from_yaml(yaml_content)
        return Ok(
            WorkflowValidation(
                valid=True,
                name=definition.name,
                workflow_type=definition.type,
                phase_count=len(definition.phases),
            )
        )

    return Ok(
        WorkflowValidation(
            valid=False,
            errors=[error_msg] if error_msg else ["Unknown validation error"],
        )
    )


def _classify_workflow_error(error_msg: str) -> WorkflowError:
    """Classify a handler error message into a WorkflowError enum value."""
    lower = error_msg.lower()
    if "active execution" in lower:
        return WorkflowError.HAS_ACTIVE_EXECUTIONS
    if "already archived" in lower:
        return WorkflowError.ALREADY_ARCHIVED
    return WorkflowError.INVALID_INPUT


async def delete_workflow(
    workflow_id: str,
) -> Result[None, WorkflowError]:
    """Archive (soft-delete) a workflow template.

    Args:
        workflow_id: ID of the workflow template to archive.

    Returns:
        Ok(None) on success, Err(WorkflowError) on failure.
    """
    from syn_domain.contexts.orchestration import (
        ArchiveWorkflowTemplateCommand,
        ArchiveWorkflowTemplateHandler,
    )

    try:
        command = ArchiveWorkflowTemplateCommand(workflow_id=workflow_id)
    except ValueError as e:
        return Err(WorkflowError.INVALID_INPUT, message=str(e))

    await ensure_connected()
    repository = get_workflow_repo()
    execution_projection = get_projection_mgr().workflow_execution_list
    publisher = get_publisher()
    handler = ArchiveWorkflowTemplateHandler(
        repository=repository,
        execution_projection=execution_projection,
        event_publisher=publisher,
    )

    result = await handler.handle(command)

    if result is None:
        return Err(WorkflowError.NOT_FOUND, message=f"Workflow {workflow_id} not found")

    if not result.success:
        error_enum = _classify_workflow_error(result.error)
        return Err(error_enum, message=result.error)

    await sync_published_events_to_projections()
    return Ok(None)


# =============================================================================
# Request Models
# =============================================================================


class CreateWorkflowRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$",
    )
    name: str
    workflow_type: str = "custom"
    classification: str = "standard"
    repository_url: str = ""
    repository_ref: str = "main"
    description: str | None = None
    project_name: str | None = None
    phases: list[dict[str, Any]] | None = None
    input_declarations: list[dict[str, Any]] | None = None
    repos: list[str] = Field(
        default_factory=list,
        description=(
            "Default GitHub URLs for this workflow template (ADR-058). "
            "Can be overridden at execution time via the repos field on the execute request."
        ),
    )
    requires_repos: bool = Field(
        default=True,
        description=(
            "Whether this workflow requires repository access at execution time (ADR-058 #666). "
            "Set to false for research or analysis workflows that don't need repos."
        ),
    )


class ValidateYamlRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    content: str | None = Field(default=None, description="Raw YAML content to validate")
    filename: str = Field(default="workflow.yaml", description="Original filename (informational)")
    file: str | None = Field(
        default=None,
        description="Deprecated — file paths are no longer supported. Use 'content' instead.",
    )


class UpdatePhasePromptRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    prompt_template: str = Field(..., min_length=1)
    model: str | None = None
    timeout_seconds: int | None = None
    allowed_tools: list[str] | None = None


# =============================================================================
# Response Models
# =============================================================================


class CreateWorkflowResponse(BaseModel):
    id: str
    name: str
    workflow_type: str
    classification: str
    repository_url: str
    requires_repos: bool
    status: str


class UpdatePhaseResponse(BaseModel):
    workflow_id: str
    phase_id: str
    status: str


class ValidateYamlResponse(BaseModel):
    valid: bool
    name: str = ""
    workflow_type: str = ""
    phase_count: int = 0
    errors: list[str] = Field(default_factory=list)


# =============================================================================
# HTTP Endpoints
# =============================================================================


@router.post("", response_model=CreateWorkflowResponse, status_code=201)
async def create_workflow_endpoint(body: CreateWorkflowRequest) -> CreateWorkflowResponse:
    """Create a new workflow template."""
    result = await create_workflow(
        name=body.name,
        workflow_type=body.workflow_type,
        classification=body.classification,
        repository_url=body.repository_url,
        repository_ref=body.repository_ref,
        description=body.description,
        project_name=body.project_name,
        phases=body.phases,
        input_declarations=body.input_declarations,
        workflow_id=body.id,
        repos=list(body.repos),
        requires_repos=body.requires_repos,
    )

    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.message)

    return CreateWorkflowResponse(
        id=result.value,
        name=body.name,
        workflow_type=body.workflow_type,
        classification=body.classification,
        repository_url=body.repository_url,
        requires_repos=body.requires_repos,
        status="created",
    )


@router.post("/validate", response_model=ValidateYamlResponse)
async def validate_yaml_endpoint(body: ValidateYamlRequest) -> ValidateYamlResponse:
    """Validate a workflow YAML definition."""
    if body.content is None and body.file is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "The 'file' field (file paths) is no longer supported. "
                "Please read the file locally and send its contents via the 'content' field."
            ),
        )
    if body.content is None:
        raise HTTPException(
            status_code=400,
            detail="The 'content' field is required.",
        )
    assert body.content is not None  # guaranteed by guards above
    result = await validate_yaml(yaml_content=body.content)

    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.message)

    v = result.value
    return ValidateYamlResponse(
        valid=v.valid,
        name=v.name or "",
        workflow_type=v.workflow_type or "",
        phase_count=v.phase_count or 0,
        errors=v.errors or [],
    )


class DeleteWorkflowResponse(BaseModel):
    workflow_id: str
    status: str


@router.delete(
    "/{workflow_id}",
    response_model=DeleteWorkflowResponse,
    summary="Archive (soft-delete) a workflow template",
    responses={
        404: {"description": "Workflow template not found"},
        409: {"description": "Conflict — workflow has active executions or is already archived"},
    },
)
async def delete_workflow_endpoint(workflow_id: str) -> DeleteWorkflowResponse:
    """Archive (soft-delete) a workflow template.

    Archived templates are excluded from listing by default but remain
    accessible via `GET /workflows/{id}` and with `?include_archived=true`.
    """
    result = await delete_workflow(workflow_id=workflow_id)
    if isinstance(result, Err):
        status_map = {
            WorkflowError.NOT_FOUND: 404,
            WorkflowError.HAS_ACTIVE_EXECUTIONS: 409,
            WorkflowError.ALREADY_ARCHIVED: 409,
        }
        status = status_map.get(result.error, 400)
        raise HTTPException(status_code=status, detail=result.message)
    return DeleteWorkflowResponse(workflow_id=workflow_id, status="archived")


# =============================================================================
# Phase Update
# =============================================================================


async def update_phase_prompt(
    workflow_id: str,
    phase_id: str,
    prompt_template: str,
    model: str | None = None,
    timeout_seconds: int | None = None,
    allowed_tools: list[str] | None = None,
) -> Result[str, WorkflowError]:
    """Update a workflow phase's prompt template and optional config.

    Args:
        workflow_id: The workflow template ID.
        phase_id: The phase to update.
        prompt_template: New prompt content.
        model: Optional model override.
        timeout_seconds: Optional timeout override.
        allowed_tools: Optional allowed tools override.

    Returns:
        Ok(workflow_id) on success, Err(WorkflowError) on failure.
    """
    from syn_domain.contexts.orchestration import (
        UpdatePhasePromptCommand,
        UpdateWorkflowPhaseHandler,
    )

    command = UpdatePhasePromptCommand(
        aggregate_id=workflow_id,
        phase_id=phase_id,
        prompt_template=prompt_template,
        model=model,
        timeout_seconds=timeout_seconds,
        allowed_tools=allowed_tools,
    )

    await ensure_connected()
    repository = get_workflow_repo()
    publisher = get_publisher()
    handler = UpdateWorkflowPhaseHandler(
        repository=repository,
        event_publisher=publisher,
    )

    try:
        result_id = await handler.handle(command)
        await sync_published_events_to_projections()
        return Ok(result_id)
    except ValueError as e:
        error_msg = str(e).lower()
        if "not found" in error_msg:
            return Err(WorkflowError.NOT_FOUND, message=str(e))
        return Err(WorkflowError.INVALID_INPUT, message=str(e))


@router.put("/{workflow_id}/phases/{phase_id}", response_model=UpdatePhaseResponse)
async def update_phase_prompt_endpoint(
    workflow_id: str,
    phase_id: str,
    body: UpdatePhasePromptRequest,
) -> UpdatePhaseResponse:
    """Update a workflow phase's prompt template and optional config."""
    result = await update_phase_prompt(
        workflow_id=workflow_id,
        phase_id=phase_id,
        prompt_template=body.prompt_template,
        model=body.model,
        timeout_seconds=body.timeout_seconds,
        allowed_tools=body.allowed_tools,
    )

    if isinstance(result, Err):
        status_code = 404 if result.error == WorkflowError.NOT_FOUND else 400
        raise HTTPException(status_code=status_code, detail=result.message)

    return UpdatePhaseResponse(
        workflow_id=workflow_id,
        phase_id=phase_id,
        status="updated",
    )


# =============================================================================
# YAML Upload (thin wrapper — server owns parsing)
# =============================================================================


_ACCEPTED_YAML_CONTENT_TYPES = frozenset(
    {
        "application/yaml",
        "application/x-yaml",
        "text/yaml",
        "text/x-yaml",
    }
)
_MAX_YAML_BYTES = 1 * 1024 * 1024  # 1 MiB — workflow definitions are small


class _YamlCreateOutcome(BaseModel):
    """Internal service-layer result: enough to build the HTTP response."""

    model_config = ConfigDict(frozen=True)
    workflow_id: str
    name: str
    workflow_type: str
    classification: str
    repository_url: str
    requires_repos: bool


async def create_workflow_from_yaml(
    yaml_content: str,
    *,
    workflow_id_override: str | None = None,
    name_override: str | None = None,
) -> Result[_YamlCreateOutcome, WorkflowError]:
    """Create a workflow template from raw YAML content.

    Server owns all YAML semantics (name, classification, repository,
    requires_repos inference per ADR-058). Query-string overrides win for
    ``name`` and ``workflow_id`` when supplied.

    Raises ``ValueError`` on malformed YAML or unresolved ``prompt_file:``
    references (no base_dir is available server-side).
    """
    import yaml
    from event_sourcing.core.errors import StreamAlreadyExistsError

    from syn_domain.contexts.orchestration import (
        CreateWorkflowTemplateHandler,
        WorkflowDefinition,
    )
    from syn_domain.contexts.orchestration._shared.yaml_to_command import (
        build_command_from_definition,
    )

    try:
        definition = WorkflowDefinition.from_yaml(yaml_content)
    except yaml.YAMLError as e:
        raise ValueError(f"Malformed YAML: {e}") from e
    command = build_command_from_definition(
        definition,
        workflow_id_override=workflow_id_override,
        name_override=name_override,
    )

    await ensure_connected()
    handler = CreateWorkflowTemplateHandler(
        repository=get_workflow_repo(),
        event_publisher=get_publisher(),
    )

    # Domain-invariant failures (invalid fields, empty phases) raise ValueError;
    # duplicate workflow ids surface as StreamAlreadyExistsError from the event
    # store. Both are user-input problems. Anything else is a bug or
    # infrastructure failure and should propagate as a 500.
    try:
        workflow_id = await handler.handle(command)
    except (ValueError, StreamAlreadyExistsError) as e:
        return Err(WorkflowError.INVALID_INPUT, message=str(e))
    await sync_published_events_to_projections()
    return Ok(
        _YamlCreateOutcome(
            workflow_id=workflow_id,
            name=command.name,
            workflow_type=command.workflow_type.value,
            classification=command.classification.value,
            repository_url=command.repository_url,
            requires_repos=command.requires_repos,
        )
    )


@router.post("/from-yaml", response_model=CreateWorkflowResponse, status_code=201)
async def create_workflow_from_yaml_endpoint(
    request: Request,
    name: str | None = None,
    workflow_id: str | None = None,
) -> CreateWorkflowResponse:
    """Create a workflow template by uploading raw YAML.

    The CLI (`syn workflow create --from <file>`) POSTs the file bytes
    here. Every semantic field (name, classification, repository,
    phases, inputs, requires_repos) comes from the YAML itself.

    Query-string ``name`` and ``workflow_id`` are optional overrides
    intended for scripted bulk installation (e.g. renaming a template
    on install). They are *not* a second source of truth for fields
    that live in the YAML.
    """
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in _ACCEPTED_YAML_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Expected YAML content-type (one of "
                f"{sorted(_ACCEPTED_YAML_CONTENT_TYPES)!r}), got {content_type!r}"
            ),
        )

    raw = await request.body()
    if len(raw) > _MAX_YAML_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"YAML body exceeds {_MAX_YAML_BYTES} bytes",
        )

    try:
        yaml_content = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=400, detail=f"YAML body is not valid UTF-8: {e}") from e

    try:
        result = await create_workflow_from_yaml(
            yaml_content,
            workflow_id_override=workflow_id,
            name_override=name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid workflow YAML: {e}") from e

    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.message)

    outcome = result.value
    return CreateWorkflowResponse(
        id=outcome.workflow_id,
        name=outcome.name,
        workflow_type=outcome.workflow_type,
        classification=outcome.classification,
        repository_url=outcome.repository_url,
        requires_repos=outcome.requires_repos,
        status="created",
    )
