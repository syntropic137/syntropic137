"""Workflow TEMPLATE command operations (create, validate).

Service functions are plain ``async def`` (importable by tests).
HTTP endpoints wire the service functions to ``@router.post()`` routes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

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
from syn_shared.agents import DEFAULT_PHASE_SANDBOX, AgentProvider

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from syn_domain.contexts.orchestration._shared.skill_ref import SkillRef
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        InputDeclaration,
        PhaseDefinition,
        WorkflowClassification,
        WorkflowType,
    )
    from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
        InstallOutcome,
    )

logger = logging.getLogger(__name__)

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


def _as_bool(value: object, field: str) -> bool:
    """Only a real bool. Anything else is the caller's error, so say so.

    `bool("false")` is True, so coercion turned `allow_delegation: "false"`
    into delegation ENABLED -- asking for the feature off and getting it on.
    The first fix silently defaulted a non-bool to False instead, which is
    fail-closed but still wrong in the other direction: `1` and `"true"`
    became False, so a caller asking for it ON silently got it OFF, with a
    201. Trading one silent corruption for another is not a fix.

    A JSON boolean literal arrives as a real bool; only a QUOTED value
    arrives as a string, and that is a malformed request, not an opinion.
    """
    if isinstance(value, bool):
        return value
    msg = f"phase field {field!r} must be a boolean, got {type(value).__name__}: {value!r}"
    raise ValueError(msg)


def _expand_skills(entries: Iterable[object] | None) -> tuple[SkillRef, ...]:
    """Expand each entry the way the YAML path does.

    Passing raw entries straight to `SkillRef` looked equivalent and is not:
    the verbose form `{"source": ..., "names": ["alpha", "beta"]}` declares
    TWO skills, and direct validation produced ONE named after the repo. So a
    caller asking for `alpha` and `beta` silently got a single skill called
    `b` -- a wrong identity rather than a missing one, which resolves and
    injects the wrong instructions.

    That is worse than the bug this PR set out to fix. `main` dropped skills
    entirely; absent is recoverable, wrong is not.
    """
    from syn_domain.contexts.orchestration._shared.skill_ref import expand_skill_entry

    if not entries:
        return ()
    expanded: list[SkillRef] = []
    for entry in entries:
        expanded.extend(expand_skill_entry(entry))
    return tuple(expanded)


def _agent_field(phase: Mapping[str, Any], name: str, default: Any = None) -> Any:  # noqa: ANN401
    """Read a phase's agent setting from either spelling.

    The packaged workflow YAML nests these under ``agent:`` -- see
    ``workflows/sdlc/research-plan/workflow.yaml`` -- while the create request
    carries them flat. Posting the YAML shape sent the whole block into a key
    nothing read, so the phase installed with no provider and no model, with a
    201 and no warning (#1011).

    A flat field wins when both are present: it is the more specific spelling,
    and picking silently either way would be a guess.
    """
    if name in phase:
        return phase[name]
    agent = phase.get("agent")
    if isinstance(agent, dict) and name in agent:
        return agent[name]
    return default


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
                # Dropping this silently reinstates the clone for a phase
                # installed through the API that declared it did not need one
                # (#1187) - the bootstrap cost the declaration exists to avoid.
                clone_repos=_as_bool(p.get("clone_repos", True), "clone_repos"),
                argument_hint=p.get("argument_hint"),
                # These four were accepted and discarded (#1011). `provider`
                # meant every codex phase installed through the API ran as
                # claude; `skills` and `claude_plugins` meant per-phase
                # injection installed nothing. The structural test in
                # test_phase_create_carries_every_field.py fails if a future
                # field is added to PhaseDefinition without being mapped here.
                model=_agent_field(p, "model"),
                provider=_agent_field(p, "provider"),
                allow_delegation=_as_bool(
                    _agent_field(p, "allow_delegation", False), "allow_delegation"
                ),
                # Dropping this silently downgrades a phase's declared
                # authority to the default, which for a review phase means it
                # can write the code it certifies (#1161). Caught by the
                # roundtrip assertion in test_phase_create_carries_every_field.
                sandbox=_agent_field(p, "sandbox", DEFAULT_PHASE_SANDBOX),
                claude_plugins=tuple(p.get("claude_plugins") or ()),
                skills=_expand_skills(p.get("skills")),
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
    version: str | None = None,
    source_digest: str | None = None,
    force: bool = False,
) -> Result[InstallOutcome, WorkflowError]:
    """Create or update a workflow template (install upsert, issue #822).

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
        version: Package version being installed, recorded for provenance.
        source_digest: Resolved source commit SHA, recorded for provenance.
        force: Overwrite an already-installed matching version.

    Returns:
        Ok(InstallOutcome) on success, Err(WorkflowError) on failure. The
        outcome reports whether anything actually changed: a byte-identical
        reinstall is a successful no-op (issue #822).
    """
    from event_sourcing import ConcurrencyConflictError, StreamAlreadyExistsError

    from syn_domain.contexts.orchestration import (
        CreateWorkflowTemplateCommand,
        CreateWorkflowTemplateHandler,
        WorkflowTemplateConflictError,
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
        version=version,
        source_digest=source_digest,
        force=force,
    )

    await ensure_connected()
    repository = get_workflow_repo()
    publisher = get_publisher()
    handler = CreateWorkflowTemplateHandler(
        repository=repository,
        event_publisher=publisher,
    )

    try:
        outcome = await handler.handle(command)
        await sync_published_events_to_projections()
        return Ok(outcome)
    except WorkflowTemplateConflictError as e:
        # Domain conflict (already installed / digest mismatch). Carries a
        # user-facing message; never event-store wording. Maps to HTTP 409.
        return Err(WorkflowError.ALREADY_EXISTS, message=str(e))
    except (ConcurrencyConflictError, StreamAlreadyExistsError) as e:
        # A genuine concurrent install of the same id. Also a 409, but the
        # event-store text is replaced with something actionable (issue #822).
        logger.warning("Concurrent install of workflow %s: %s", command.aggregate_id, e)
        return Err(
            WorkflowError.ALREADY_EXISTS,
            message=(
                f"Workflow '{command.aggregate_id}' was modified by another request "
                f"while this install was in flight. Retry the install."
            ),
        )
    except ValueError as e:
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
    version: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "Package version being installed (issue #822). Recorded on the template "
            "so an execution can be traced to the version that produced it. "
            "Reinstalling a matching version is refused unless force is set."
        ),
    )
    source_digest: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "Resolved source commit SHA for the package content (issue #822). "
            "A matching version resolving to a different digest is refused: that is "
            "the signature of a republished version."
        ),
    )
    force: bool = Field(
        default=False,
        description="Overwrite an already-installed matching version.",
    )


class ValidateYamlRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    content: str | None = Field(default=None, description="Raw YAML content to validate")
    filename: str = Field(default="workflow.yaml", description="Original filename (informational)")
    file: str | None = Field(
        default=None,
        description="Deprecated; file paths are no longer supported. Use 'content' instead.",
    )


class UpdatePhasePromptRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    prompt_template: str = Field(..., min_length=1)
    model: str | None = None
    provider: str | None = None
    timeout_seconds: int | None = None
    allowed_tools: list[str] | None = None

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, value: str | None) -> str | None:
        """Reject unsupported provider values at the API boundary.

        Without this an unknown provider (typo) persists, then execution silently
        falls through to the Claude path while telemetry reports the bad value.
        """
        if value is not None and value not in set(AgentProvider):
            allowed = ", ".join(sorted(AgentProvider))
            msg = f"provider must be one of: {allowed}"
            raise ValueError(msg)
        return value


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
        version=body.version,
        source_digest=body.source_digest,
        force=body.force,
    )

    if isinstance(result, Err):
        # A conflict is not bad input: the request was well formed and the
        # server refused it against existing state (issue #822).
        status_code = 409 if result.error == WorkflowError.ALREADY_EXISTS else 400
        raise HTTPException(status_code=status_code, detail=result.message)

    return CreateWorkflowResponse(
        id=result.value.workflow_id,
        name=body.name,
        workflow_type=body.workflow_type,
        classification=body.classification,
        repository_url=body.repository_url,
        requires_repos=body.requires_repos,
        status="created" if result.value.changed else "unchanged",
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
        409: {"description": "Conflict; workflow has active executions or is already archived"},
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
    provider: str | None = None,
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
        provider=provider,
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
        provider=body.provider,
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
# YAML Upload (thin wrapper; server owns parsing)
# =============================================================================


_ACCEPTED_YAML_CONTENT_TYPES = frozenset(
    {
        "application/yaml",
        "application/x-yaml",
        "text/yaml",
        "text/x-yaml",
        # WHY json: every JSON document is a valid YAML document, and the
        # parser below is yaml.safe_load either way. `syn workflow install`
        # uploads a RESOLVED definition (prompt_file refs already inlined
        # against the package directory), which it must serialize itself; it
        # has no YAML emitter, and hand-rolling one around arbitrary prompt
        # bodies is where emitters get subtly wrong. Accepting JSON costs this
        # endpoint nothing and keeps the CLI dependency-free.
        "application/json",
    }
)
_MAX_YAML_BYTES = 1 * 1024 * 1024  # 1 MiB; workflow definitions are small


class _YamlCreateOutcome(BaseModel):
    """Internal service-layer result: enough to build the HTTP response."""

    model_config = ConfigDict(frozen=True)
    workflow_id: str
    name: str
    workflow_type: str
    classification: str
    repository_url: str
    requires_repos: bool
    changed: bool = True
    """False when the package was already installed byte-identical (#822)."""


async def create_workflow_from_yaml(
    yaml_content: str,
    *,
    workflow_id_override: str | None = None,
    name_override: str | None = None,
    version: str | None = None,
    source_digest: str | None = None,
    force: bool = False,
) -> Result[_YamlCreateOutcome, WorkflowError]:
    """Create a workflow template from raw YAML content.

    Server owns all YAML semantics (name, classification, repository,
    requires_repos inference per ADR-058). Query-string overrides win for
    ``name`` and ``workflow_id`` when supplied.

    Raises ``ValueError`` on malformed YAML or unresolved ``prompt_file:``
    references (no base_dir is available server-side). Raises
    ``ClaudePluginError`` (any subclass) if a referenced claude plugin is
    not yet present in the lock projection -- per the #726 Phase A design
    the API does not fetch; the CLI must register plugins via
    ``POST /claude-plugins/registrations`` first. The endpoint wrapper maps
    both error families to the right HTTP status.
    """
    import yaml
    from event_sourcing.core.errors import ConcurrencyConflictError, StreamAlreadyExistsError

    from syn_api._wiring import get_claude_plugin_resolution_service
    from syn_domain.contexts.orchestration import (
        CreateWorkflowTemplateHandler,
        WorkflowDefinition,
        WorkflowTemplateConflictError,
        build_command_from_definition,
    )

    try:
        definition = WorkflowDefinition.from_yaml(yaml_content)
    except yaml.YAMLError as e:
        raise ValueError(f"Malformed YAML: {e}") from e

    # Implicit fetch: any claude_plugins ref the YAML declares must be
    # present in the lock projection before we register the workflow.
    # ClaudePluginError subclasses propagate to the endpoint wrapper, which
    # translates them to HTTP 422 with a stable error_code. The workflow is
    # NOT registered if any plugin fetch fails (no partial state).
    resolution_service = await get_claude_plugin_resolution_service()
    await resolution_service.ensure_registered(definition)

    command = build_command_from_definition(
        definition,
        workflow_id_override=workflow_id_override,
        name_override=name_override,
        version=version,
        source_digest=source_digest,
        force=force,
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
        outcome = await handler.handle(command)
    except WorkflowTemplateConflictError as e:
        # Already installed / republished digest. A refusal against existing
        # state, not bad input, so it maps to 409 (issue #822).
        return Err(WorkflowError.ALREADY_EXISTS, message=str(e))
    except (ConcurrencyConflictError, StreamAlreadyExistsError) as e:
        logger.warning("Concurrent install of workflow %s: %s", command.aggregate_id, e)
        return Err(
            WorkflowError.ALREADY_EXISTS,
            message=(
                f"Workflow '{command.aggregate_id}' was modified by another request "
                f"while this install was in flight. Retry the install."
            ),
        )
    except ValueError as e:
        return Err(WorkflowError.INVALID_INPUT, message=str(e))
    await sync_published_events_to_projections()
    return Ok(
        _YamlCreateOutcome(
            workflow_id=outcome.workflow_id,
            changed=outcome.changed,
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
    version: str | None = None,
    source_digest: str | None = None,
    force: bool = False,
) -> CreateWorkflowResponse:
    """Create a workflow template by uploading raw YAML.

    The CLI (`syn workflow create --from <file>`) POSTs the file bytes
    here. Every semantic field (name, classification, repository,
    phases, inputs, requires_repos) comes from the YAML itself.

    Query-string ``name`` and ``workflow_id`` are optional overrides
    intended for scripted bulk installation (e.g. renaming a template
    on install). They are *not* a second source of truth for fields
    that live in the YAML.

    ``version``, ``source_digest`` and ``force`` carry install provenance
    and policy (issue #822). ``syn workflow install`` supplies the package
    version and the resolved commit SHA; reinstalling a matching version is
    refused with 409 unless ``force`` is set, and a matching version that
    resolves to a different digest is refused regardless of how it looks,
    because that is the signature of a republished version.
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

    from syn_api.services.claude_plugin_error_mapping import (
        http_exception_for_claude_plugin_error,
    )
    from syn_domain.contexts.orchestration import (
        ClaudePluginError,
    )

    try:
        result = await create_workflow_from_yaml(
            yaml_content,
            workflow_id_override=workflow_id,
            name_override=name,
            version=version,
            source_digest=source_digest,
            force=force,
        )
    except ClaudePluginError as e:
        # Stable error_code (claude_plugin_unreachable, etc.) so CLI/dashboard
        # can render actionable messages without string sniffing.
        raise http_exception_for_claude_plugin_error(e) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid workflow YAML: {e}") from e

    if isinstance(result, Err):
        status_code = 409 if result.error == WorkflowError.ALREADY_EXISTS else 400
        raise HTTPException(status_code=status_code, detail=result.message)

    outcome = result.value
    return CreateWorkflowResponse(
        id=outcome.workflow_id,
        name=outcome.name,
        workflow_type=outcome.workflow_type,
        classification=outcome.classification,
        repository_url=outcome.repository_url,
        requires_repos=outcome.requires_repos,
        status="created" if outcome.changed else "unchanged",
    )
