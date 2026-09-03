"""ExecuteWorkflow command handler — VSA compliance wrapper.

Delegates to WorkflowExecutionProcessor (ISS-196 Processor To-Do List pattern).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from event_sourcing import StreamAlreadyExistsError

from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseExecutionType,
    require_supported_execution_type,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    DuplicateExecutionError,
    UnsupportedToolPolicyForProviderError,
    WorkflowNotFoundError,
)
from syn_shared.agents import AgentProvider, require_executable_provider
from syn_shared.tools import require_supported_tools

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.claude_plugin_ref import (
        ClaudePluginRef,
    )
    from syn_domain.contexts.orchestration._shared.resolved_claude_plugin import (
        ResolvedClaudePlugin,
    )
    from syn_domain.contexts.orchestration._shared.resolved_skill import (
        ResolvedSkill,
    )
    from syn_domain.contexts.orchestration._shared.skill_ref import (
        SkillRef,
    )
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

# WHY (issue #726, PR2): the resolver is injected as a callable so the
# domain handler does not import the application service. The wiring layer
# binds this to ``ClaudePluginResolutionService.resolve_for_phase``.
PhasePluginResolver = Callable[
    ["Sequence[ClaudePluginRef]", "Sequence[ClaudePluginRef]"],
    Awaitable["tuple[ResolvedClaudePlugin, ...]"],
]

# WHY (issue #772): mirrors PhasePluginResolver. The wiring layer binds this
# to ``SkillResolutionService.resolve_for_phase``.
PhaseSkillResolver = Callable[
    ["Sequence[SkillRef]", "Sequence[SkillRef]"],
    Awaitable["tuple[ResolvedSkill, ...]"],
]

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


def validate_phase_declarations(workflow: WorkflowTemplateAggregate) -> None:
    """Raise if any stored phase declares something the platform cannot honour.

    THE single definition of that check (#1039). Three entry points need it and
    each one previously would have grown its own copy:

    - the HTTP route, so a caller gets a 422 instead of a 200 carrying an
      execution id that will never resolve;
    - the trigger dispatcher, so the dispatch record can be marked `failed`
      rather than `dispatched` for a run that cannot happen;
    - `_get_executable_phases` below, which is the boundary that actually
      protects the CLI and any future caller.

    All three matter because a stored template is rehydrated from its
    historical ``WorkflowTemplateCreated`` event and never sees the YAML
    validator, so authoring-time refusal reaches none of them.
    """
    for phase in workflow.phases:
        phase_id = getattr(phase, "phase_id", None)
        require_supported_execution_type(
            getattr(phase, "execution_type", PhaseExecutionType.SEQUENTIAL),
            phase_id=phase_id,
        )
        tools = require_supported_tools(
            tuple(getattr(phase, "allowed_tools", ()) or ()),
            phase_id=phase_id,
        )
        provider = getattr(phase, "provider", None) or AgentProvider.CLAUDE
        if tools and provider == AgentProvider.CODEX:
            raise UnsupportedToolPolicyForProviderError(
                provider=str(provider), phase_id=phase_id, declared=list(tools)
            )


def _build_agent_config_from_phase(phase: object) -> AgentConfiguration:
    """Build an AgentConfiguration from a workflow-template phase.

    The YAML `agent:` block contributes `provider` and `allow_delegation`;
    the top-level `model` field feeds the model. All are optional;
    AgentConfiguration's defaults apply when none are set.

    This is the EXECUTION boundary for provider validity. It runs for every
    phase of every execution - API, GitHub trigger and CLI alike - before any
    workspace is provisioned or any execution stream is created. YAML parsing
    rejects the removed ``claude-interactive`` provider, but a template stored
    before the removal is rehydrated straight from its historical
    ``WorkflowTemplateCreated`` event and never sees the YAML validator; the
    aggregate stays permissive on purpose so operators can still read and fix
    those templates. Validating here is what stops such a phase from falling
    through to ``claude -p`` and reporting a headless SUCCESS.
    """
    phase_model: str | None = getattr(phase, "model", None)
    phase_provider: str | None = getattr(phase, "provider", None)
    allow_delegation: bool = bool(getattr(phase, "allow_delegation", False))
    phase_id: str | None = getattr(phase, "phase_id", None)
    # Canonicalise here, not just in the YAML validator: a stored template
    # never saw that validator. Unknown names are refused rather than
    # dropped - dropping would restrict a phase to whatever happened to be
    # spelled correctly and silently remove the rest.
    allowed_tools: tuple[str, ...] = require_supported_tools(
        tuple(getattr(phase, "allowed_tools", ()) or ()), phase_id=phase_id
    )
    defaults = AgentConfiguration()
    resolved_provider = phase_provider or defaults.provider
    provider = require_executable_provider(resolved_provider, phase_id=phase_id)
    # Codex has no tool vocabulary (ADR-069 section 3), so this combination can
    # never be honoured. The YAML validator refuses it at authoring time, but a
    # stored template bypasses that, and the only other guard is in the command
    # builder - which runs AFTER the workspace is provisioned and paid for.
    # Two installed workflows carry exactly this shape today.
    if provider is AgentProvider.CODEX and allowed_tools:
        raise UnsupportedToolPolicyForProviderError(
            provider=str(provider), phase_id=phase_id, declared=list(allowed_tools)
        )
    # `allowed_tools` MUST be part of this condition, not only of the
    # constructor below (#1039). A phase that scopes its tools and accepts the
    # default model and provider is the commonest tool-scoping shape there is,
    # and it takes this branch - so a constructor-only fix drops the grant for
    # exactly the author who asked for it, while passing any test that also
    # sets a model. Pinned by
    # test_tools_survive_when_they_are_the_only_thing_declared.
    if not (phase_model or phase_provider or allow_delegation or allowed_tools):
        return defaults
    return AgentConfiguration(
        provider=resolved_provider,
        model=phase_model,
        allow_delegation=allow_delegation,
        allowed_tools=allowed_tools,
    )


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
        phase_plugin_resolver: PhasePluginResolver | None = None,
        phase_skill_resolver: PhaseSkillResolver | None = None,
    ) -> None:
        self._processor = processor
        self._workflow_repo = workflow_repository
        # WHY optional (issue #726, PR2): pre-PR2 callers and the in-process
        # smoke tests construct the handler without a resolver. When None,
        # ``_get_executable_phases`` leaves ``ExecutablePhase.claude_plugins``
        # at its empty default and PR1 behaviour is preserved.
        self._phase_plugin_resolver = phase_plugin_resolver
        # WHY optional (issue #772): mirrors phase_plugin_resolver. When None,
        # ``ExecutablePhase.skills`` stays at its empty default.
        self._phase_skill_resolver = phase_skill_resolver

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

        phases = await self._get_executable_phases(workflow)
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

    async def validate_stored_declarations(self, workflow_id: str) -> None:
        """Apply `validate_phase_declarations` to a stored template, by id.

        Exists so a caller that has not loaded the aggregate - the trigger
        dispatcher - can refuse a bad template BEFORE acknowledging the
        dispatch, without reaching into this handler's repository.

        A missing workflow is NOT this check's business: `handle()` raises
        `WorkflowNotFoundError` for that, and duplicating the decision here
        would give two entry points different answers for the same id.
        """
        workflow = await self._workflow_repo.get_by_id(workflow_id)
        if workflow is not None:
            validate_phase_declarations(workflow)

    async def _get_executable_phases(
        self,
        workflow: WorkflowTemplateAggregate,
    ) -> list[ExecutablePhase]:
        """Convert workflow template phases to executable phases.

        WHY async (issue #726, PR2): the per-phase claude-plugin resolution
        reads the lock projection, which is async. ``ExecutablePhase`` is
        otherwise a pure value object construction.
        """
        # WHY single resolver call per phase: keeps each phase's
        # ``ExecutablePhase.claude_plugins`` populated exactly once, even
        # though the workflow-scope refs are the same across all phases.
        # Resolution unions global + workflow + phase scopes per phase.
        workflow_refs = workflow.claude_plugins
        workflow_skill_refs = workflow.skills
        executable_phases: list[ExecutablePhase] = []
        for phase in workflow.phases:
            # EXECUTION-BOUNDARY re-check, not a duplicate of the YAML rule.
            # A template stored before that rule existed is rehydrated from its
            # historical `WorkflowTemplateCreated` event and never sees the
            # loader, exactly as the provider guard below documents. Checking
            # only at authoring would let every already-stored `parallel` phase
            # through - the population most likely to have one.
            require_supported_execution_type(
                getattr(phase, "execution_type", PhaseExecutionType.SEQUENTIAL),
                phase_id=getattr(phase, "phase_id", None),
            )
            agent_config = _build_agent_config_from_phase(phase)
            resolved = await self._resolve_phase_plugins(
                workflow_refs=workflow_refs,
                phase_refs=list(phase.claude_plugins),
            )
            resolved_skills = await self._resolve_phase_skills(
                workflow_refs=workflow_skill_refs,
                phase_refs=list(phase.skills),
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
                    claude_plugins=resolved,
                    skills=resolved_skills,
                    asserts=tuple(phase.asserts),
                )
            )
        return executable_phases

    async def _resolve_phase_plugins(
        self,
        workflow_refs: Sequence[ClaudePluginRef],
        phase_refs: Sequence[ClaudePluginRef],
    ) -> tuple[ResolvedClaudePlugin, ...]:
        """Delegate to the injected resolver, falling back to empty for legacy paths."""
        if self._phase_plugin_resolver is None:
            return ()
        if not workflow_refs and not phase_refs:
            # WHY short-circuit: avoids touching the lock projection when
            # neither scope declares plugins. The global scope still applies
            # via the resolver, but skipping the call when both local scopes
            # are empty matches PR1 behavior for workflows that pre-date #726.
            empty_global = await self._phase_plugin_resolver([], [])
            return empty_global
        return await self._phase_plugin_resolver(workflow_refs, phase_refs)

    async def _resolve_phase_skills(
        self,
        workflow_refs: Sequence[SkillRef],
        phase_refs: Sequence[SkillRef],
    ) -> tuple[ResolvedSkill, ...]:
        """Delegate to the injected skill resolver (issue #772).

        Mirrors ``_resolve_phase_plugins``. Unlike claude plugins, skills have
        no global scope in this plan, so (unlike the plugin path) there is no
        need to call the resolver when both scopes are empty -- an empty
        result is correct without touching the lock projection.
        """
        if self._phase_skill_resolver is None or (not workflow_refs and not phase_refs):
            return ()
        return await self._phase_skill_resolver(workflow_refs, phase_refs)
