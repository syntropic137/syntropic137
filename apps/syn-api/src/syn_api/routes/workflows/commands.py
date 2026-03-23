"""Workflow TEMPLATE command operations (create, validate).

Service functions are plain ``async def`` (importable by tests).
No HTTP endpoints currently — these are called from CLI or other services.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from syn_api._wiring import (
    ensure_connected,
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
    from syn_api.auth import AuthContext


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
    from syn_domain.contexts.orchestration._shared.WorkflowValueObjects import (
        PhaseDefinition,
        WorkflowClassification,
        WorkflowType,
    )
    from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
        CreateWorkflowTemplateCommand,
    )
    from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
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

    from syn_domain.contexts.orchestration._shared.workflow_definition import (
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
