"""Build CreateWorkflowTemplateCommand from a parsed WorkflowDefinition.

Single source of truth for the mapping between YAML workflow definitions
and the create-template command. Used by both the seeder
(``SeedWorkflowService``) and the HTTP YAML-upload endpoint
(``POST /workflows/from-yaml``) so installation via either path applies
the same ADR-058 ``requires_repos`` inference and ``WorkflowType``
fallback rules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    WorkflowType,
)
from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
    CreateWorkflowTemplateCommand,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.workflow_definition import (
        WorkflowDefinition,
    )


def infer_requires_repos(definition: WorkflowDefinition) -> bool:
    """ADR-058: explicit ``requires_repos`` wins; otherwise default to True (opt-out).

    The platform's primary use case is running workflows against repos, so the
    default favors that path. Research/no-repo workflows must opt out with
    ``requires_repos: false``.
    """
    if definition.requires_repos is not None:
        return definition.requires_repos
    return True


def build_command_from_definition(
    definition: WorkflowDefinition,
    *,
    workflow_id_override: str | None = None,
    name_override: str | None = None,
    version: str | None = None,
    source_digest: str | None = None,
    force: bool = False,
) -> CreateWorkflowTemplateCommand:
    """Build a CreateWorkflowTemplateCommand from a parsed WorkflowDefinition.

    Args:
        definition: Parsed workflow definition from YAML.
        workflow_id_override: If set, overrides ``definition.id``.
        name_override: If set, overrides ``definition.name``.
        version: Package version being installed, recorded for provenance (#822).
        source_digest: Resolved source commit SHA, recorded for provenance (#822).
        force: Overwrite an already-installed matching version (#822).

    Returns:
        Command ready to dispatch through ``CreateWorkflowTemplateHandler``.
    """
    try:
        workflow_type = WorkflowType(definition.type)
    except ValueError:
        workflow_type = WorkflowType.CUSTOM
    return CreateWorkflowTemplateCommand(
        version=version,
        source_digest=source_digest,
        force=force,
        aggregate_id=workflow_id_override or definition.id,
        name=name_override or definition.name,
        workflow_type=workflow_type,
        classification=definition.classification,
        repository_url=(definition.repository.url if definition.repository else ""),
        repository_ref=(definition.repository.ref if definition.repository else "main"),
        phases=definition.get_domain_phases(),
        project_name=definition.project_name,
        description=definition.description,
        input_declarations=definition.get_domain_input_declarations(),
        requires_repos=infer_requires_repos(definition),
        # WHY (issue #726, PR2): carry workflow-scope claude_plugins from YAML
        # into the create command so the aggregate persists them; PR2's
        # resolution service unions them with per-phase refs at execute time.
        claude_plugins=list(definition.claude_plugins),
        # WHY (issue #772): carry workflow-scope skills alongside
        # claude_plugins into the create command so the aggregate persists
        # them, mirroring the claude_plugins wiring above.
        skills=list(definition.skills),
    )
