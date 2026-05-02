"""ExecuteWorkflow command handler — VSA compliance wrapper.

Delegates to WorkflowExecutionProcessor (ISS-196 Processor To-Do List pattern).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from event_sourcing import StreamAlreadyExistsError

from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    DuplicateExecutionError,
    WorkflowNotFoundError,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )
    from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
        ExecuteWorkflowCommand,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
        WorkflowExecutionProcessor,
        WorkflowExecutionResult,
    )

logger = logging.getLogger(__name__)


def _resolve_repo_url(
    workflow: WorkflowTemplateAggregate,
    merged_inputs: dict[str, str],
) -> str | None:
    """Resolve placeholders in workflow._repository_url and guard against unresolved ones."""
    repo_url: str | None = getattr(workflow, "_repository_url", None)
    if not repo_url:
        return repo_url
    for key, value in merged_inputs.items():
        repo_url = repo_url.replace(f"{{{{{key}}}}}", str(value))
    if "{{" in repo_url:
        unresolved = re.findall(r"\{\{(\w+)\}\}", repo_url)
        if unresolved:
            msg = (
                f"Repository URL contains unresolved placeholders: {unresolved}. "
                f"Provide them via inputs (e.g., {unresolved[0]}=<value>)."
            )
        else:
            msg = (
                "Repository URL contains malformed placeholders. "
                "Use the format {{name}} with alphanumeric/underscore characters."
            )
        raise ValueError(msg)
    return repo_url


def _substitute_repo_vars(repo_url: str, merged_inputs: dict[str, str]) -> str:
    """Apply {{key}} substitution to a repo URL; raise ValueError if placeholders remain."""
    for key, value in merged_inputs.items():
        repo_url = repo_url.replace(f"{{{{{key}}}}}", str(value))
    if "{{" in repo_url:
        unresolved = re.findall(r"\{\{(\w+)\}\}", repo_url)
        if not unresolved:
            raise ValueError(
                "Malformed placeholders in repos field. "
                "Expected placeholders in the form {{name}} with alphanumeric/underscore characters."
            )
        raise ValueError(
            f"Unresolved placeholders in repos field: {unresolved}. "
            f"Provide them via inputs: {', '.join(f'{k}=<value>' for k in unresolved)}."
        )
    return repo_url


def _normalise_repo_url(url: str) -> str:
    """Expand 'owner/repo' slugs (left over in template fields) to full HTTPS URLs.

    Workflow YAML templates often declare ``repos: [owner/repo]`` rather than full
    URLs. Cross-context callers (API route, trigger dispatcher) translate to typed
    ``RepositoryRef`` at the boundary - those callers don't go through this helper.
    """
    if url.startswith(("https://", "http://", "git@")):
        return url
    parts = url.split("/")
    if len(parts) == 2:  # owner/repo slug
        return f"https://github.com/{url}"
    return url


# ADR-063 §3: keys reserved for repository identity at cross-context boundaries.
# If these appear in ``command.inputs`` it means a producer skipped the typed
# translation step (API route or BackgroundWorkflowDispatcher) and tried to smuggle
# repo identity through the generic inputs dict. We fail loudly instead of silently
# resolving them - the loud error makes the missed translation obvious in tests
# rather than letting "zero repos" propagate silently into a workflow execution.
_RESERVED_REPO_INPUT_KEYS: frozenset[str] = frozenset({"repos", "repository"})


def _resolve_repos_from_template(
    merged_inputs: dict[str, str],
    workflow: WorkflowTemplateAggregate,
) -> list[RepositoryRef]:
    """Resolve repos from workflow template fields (NOT from inputs dict).

    Two template-level sources are checked, in order:
    1. ``workflow.repos`` - list with optional ``{{var}}`` substitution
    2. ``workflow.repository_url`` - single-repo template fallback

    Returns typed ``RepositoryRef`` per ADR-063: template strings are
    parsed at this last string boundary so downstream consumers can rely
    on a single canonical representation.
    """
    if workflow.repos:
        return [
            RepositoryRef.parse(_normalise_repo_url(_substitute_repo_vars(r, merged_inputs)))
            for r in workflow.repos
        ]

    repo_url = _resolve_repo_url(workflow, merged_inputs)
    if repo_url:
        return [RepositoryRef.parse(repo_url)]
    return []


class WorkflowRepository(Protocol):
    """Repository protocol for Workflow aggregates."""

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None: ...


class ExecuteWorkflowHandler:
    """Handler for ExecuteWorkflow command (VSA compliance).

    Loads the workflow template, extracts phases, and delegates
    to WorkflowExecutionProcessor for event-driven execution.
    """

    def __init__(
        self,
        processor: WorkflowExecutionProcessor,
        workflow_repository: WorkflowRepository,
    ) -> None:
        self._processor = processor
        self._workflow_repo = workflow_repository

    async def handle(
        self,
        command: ExecuteWorkflowCommand,
    ) -> WorkflowExecutionResult:
        """Handle ExecuteWorkflow command.

        Args:
            command: ExecuteWorkflowCommand with workflow ID and inputs

        Returns:
            WorkflowExecutionResult with execution details and metrics

        Raises:
            WorkflowNotFoundError: If workflow doesn't exist
        """
        workflow = await self._workflow_repo.get_by_id(command.aggregate_id)
        if workflow is None:
            raise WorkflowNotFoundError(command.aggregate_id)

        phases = self._get_executable_phases(workflow)
        merged_inputs = self._merge_inputs(command, workflow)
        repos = (
            self._resolve_repos(command, merged_inputs, workflow) if workflow.requires_repos else []
        )

        execution_id = (
            command.execution_id
            if command.execution_id and command.execution_id.startswith("exec-")
            else f"exec-{uuid4().hex[:12]}"
        )

        try:
            return await self._processor.run(
                workflow_id=command.aggregate_id,
                workflow_name=workflow.name or "",
                phases=phases,
                inputs=merged_inputs,
                execution_id=execution_id,
                repos=repos,
            )
        except StreamAlreadyExistsError:
            logger.warning(
                "Duplicate dispatch detected for execution %s, skipping",
                execution_id,
            )
            raise DuplicateExecutionError(execution_id) from None

    @staticmethod
    def _merge_inputs(
        command: ExecuteWorkflowCommand,
        workflow: WorkflowTemplateAggregate,
    ) -> dict[str, str]:
        """Merge input_declarations defaults and task field into command inputs."""
        merged: dict[str, str] = dict(command.inputs)
        for decl in workflow.input_declarations:
            if decl.default is not None and decl.name not in merged:
                merged[decl.name] = str(decl.default)
        if command.task is not None:
            merged["task"] = command.task
        return merged

    @staticmethod
    def _resolve_repos(
        command: ExecuteWorkflowCommand,
        merged_inputs: dict[str, str],
        workflow: WorkflowTemplateAggregate,
    ) -> list[RepositoryRef]:
        """Resolve repos: typed ``command.repos`` first, else workflow template fields.

        Per ADR-063, repository identity must be passed across context boundaries
        as typed ``RepositoryRef`` on the command. This handler does NOT inspect
        ``inputs`` for repo keys - that path was removed when boundaries were typed.
        Producers (API route, ``BackgroundWorkflowDispatcher``) own the translation.
        Returns typed refs end-to-end; the processor and downstream handlers
        consume the canonical form via ``r.https_url`` at their respective seams.
        """
        if command.repos:
            return list(command.repos)

        # Guard: if a producer left repo identity in inputs without populating
        # command.repos, that's a missed boundary translation - fail loud (ADR-063).
        leaked = _RESERVED_REPO_INPUT_KEYS & merged_inputs.keys()
        if leaked:
            keys = ", ".join(sorted(leaked))
            raise ValueError(
                f"inputs[{keys}] is set but command.repos is empty. "
                f"Repository identity must be passed as RepositoryRef on the command "
                f"(ADR-063); the producing context skipped the boundary translation."
            )

        return _resolve_repos_from_template(merged_inputs, workflow)

    @staticmethod
    def _get_executable_phases(
        workflow: WorkflowTemplateAggregate,
    ) -> list[ExecutablePhase]:
        """Convert workflow template phases to executable phases."""
        executable_phases = []
        for phase in workflow.phases:
            phase_model = getattr(phase, "model", None)
            agent_config = (
                AgentConfiguration(model=phase_model) if phase_model else AgentConfiguration()
            )
            executable_phases.append(
                ExecutablePhase(
                    phase_id=phase.phase_id,
                    name=phase.name,
                    order=phase.order,
                    description=phase.description,
                    agent_config=agent_config,
                    prompt_template=phase.prompt_template or "",
                    output_artifact_type=(
                        phase.output_artifact_types[0] if phase.output_artifact_types else "text"
                    ),
                    timeout_seconds=phase.timeout_seconds,
                )
            )
        return executable_phases
