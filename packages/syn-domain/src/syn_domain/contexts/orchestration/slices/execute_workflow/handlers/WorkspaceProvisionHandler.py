"""WorkspaceProvisionHandler — creates workspace and injects secrets/artifacts (ISS-196).

Extracted from WorkflowExecutionEngine._setup_workspace_for_phase() and
workspace creation (lines 944-958, 1147-1217).

Reports ProvisionWorkspaceCompletedCommand to the aggregate.

ADR-058: Repos are pre-cloned during setup phase. After setup, synthetic
/workspace/AGENTS.md and /workspace/CLAUDE.md are injected with @-imports
of each repo's distinct instruction files, so Claude starts fully hydrated.
Where codex may run, those files' content is also installed as codex's global
instructions, because codex does not expand @-imports (#1835).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.command_phase import PhaseKind
from syn_domain.contexts.orchestration._shared.skill_errors import SkillInstallFailed
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
    SourceCommit,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ProvisionWorkspaceCompletedCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.checkout_verification import (
    verify_provisioned_checkout,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    NonZeroExitError,
    PinnedCommitUnreachableError,
    ProvisionStep,
    ProvisionStepTimeoutError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.agent_env import (
    build_agent_env,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.codex_sandbox_probe import (
    require_codex_sandbox,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.instruction_imports import (
    CODEX_INSTRUCTIONS_STAGED,
    CODEX_POINTER,
    inline_instruction_files,
    install_codex_instructions,
    repo_instruction_imports,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.repo_identity import (
    cloned_pins,
    repo_identity_env,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.skill_install import (
    install_skill,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import FallbackLaunch
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    PhaseOutputCache,
)
from syn_shared.agents import AgentProvider, require_executable_provider
from syn_shared.env_constants import (
    ENV_SYN_PHASE_DEADLINE,
)
from syn_shared.process_exit import describe_process_failure

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from typing import Protocol

    from syn_adapters.workspace_backends.service import SetupPhaseSecrets, WorkspaceService
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration._shared.resolved_claude_plugin import (
        ResolvedClaudePlugin,
    )
    from syn_domain.contexts.orchestration._shared.resolved_skill import ResolvedSkill
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
        TodoItem,
    )
    from syn_domain.contexts.orchestration._shared.workspace_credential_policy import (
        WorkspaceCredentialPolicy,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
        ArtifactCollector,
    )

    class ClaudePluginMaterializerProtocol(Protocol):
        """Minimal surface the handler needs (issue #726, PR2).

        The concrete implementation lives in ``syn_api.services``; the
        handler depends only on the structural protocol so the domain layer
        does not import the application service module.
        """

        async def fetch_for_workspace(
            self,
            plugins: tuple[ResolvedClaudePlugin, ...],
        ) -> list[tuple[str, bytes]]: ...

    class SkillMaterializerProtocol(Protocol):
        """Minimal surface the handler needs (issue #772).

        Mirrors ``ClaudePluginMaterializerProtocol``: the concrete
        implementation (``syn_api.services.skill_materializer.SkillMaterializer``)
        lives in the application layer, so the domain handler depends only on
        this structural protocol.
        """

        async def fetch_for_workspace(
            self,
            skills: tuple[ResolvedSkill, ...],
        ) -> list[tuple[str, bytes]]: ...


logger = logging.getLogger(__name__)

# Maps our phase provider values onto the vercel skills-cli --agent keys.
# The skills CLI (pinned 1.5.14 in the workspace images) owns the per-harness
# install location; we only translate our identifier vocabulary to theirs.
# Verify against `skills add --help` inside the image whenever the pin bumps.
_SKILLS_CLI_AGENT_KEYS: dict[str, str] = {
    "claude": "claude-code",
    "codex": "codex",
    "gemini": "gemini-cli",
}

# Baked delegation skills live in the agentic-workspace image under this root
# (claude-cli manifest plugins.include: delegation). A delegation-enabled phase
# installs the skill teaching its PRIMARY agent to hand off to the OTHER CLI.
_DELEGATION_SKILL_ROOT = "/opt/agentic/plugins/delegation/skills"
_DELEGATION_TARGET_SKILL: dict[str, str] = {
    AgentProvider.CODEX: "delegating-to-claude-p",  # codex learns to call claude -p
    AgentProvider.CLAUDE: "delegating-to-codex",  # claude learns to call codex exec
}


# Callable types for dependency injection
PromptBuilder = Callable[
    [ExecutablePhase, str, str, str | None, dict[str, str], dict[str, object]],
    Awaitable[str],
]
CommandBuilder = Callable[[ExecutablePhase, str], list[str]]


def _auth_staging_for(provider: str, allow_delegation: bool) -> tuple[bool, bool]:
    """Return ``(include_codex_auth, needs_claude_env)`` for a phase.

    Delegation opt-in stages BOTH auths so the primary agent can shell out to
    the other CLI; otherwise auth is scoped to the phase's single provider (the
    codex ``~/.codex/auth.json`` file for codex phases, the claude env
    otherwise).

    Validates the provider first: ``!= AgentProvider.CODEX`` is a fall-through
    that would hand claude credentials to any unrecognised provider, so an
    unrunnable one must fail before auth is staged into a workspace.
    """
    known = require_executable_provider(provider)
    include_codex_auth = allow_delegation or known is AgentProvider.CODEX
    needs_claude_env = allow_delegation or known is not AgentProvider.CODEX
    return include_codex_auth, needs_claude_env


def _codex_auth_staged_for(phase: ExecutablePhase) -> bool:
    """Whether the workspace gets ``~/.codex/auth.json``: for the phase's agent OR its fallback.

    THE FALLBACK'S CREDENTIAL IS STAGED UP FRONT, deliberately (PC-83). The
    workspace is hydrated once, before the agent runs, and the fallback runs
    in that same workspace after the primary failed - there is no later point
    at which to stage it. So a claude phase declaring a codex fallback has
    the codex auth file in its workspace for the whole phase. Declaring the
    fallback IS asking for that; a phase that declares none is unchanged.
    """
    agents = (phase.agent_config, *((phase.fallback_agent,) if phase.fallback_agent else ()))
    return any(_auth_staging_for(a.provider, a.allow_delegation)[0] for a in agents)


def _agents_that_may_run(phase: ExecutablePhase) -> frozenset[AgentProvider]:
    """Every provider whose CLI may run in this phase's workspace.

    The phase's agent, its fallback (PC-83: it runs in the same workspace after
    the primary failed), and, under ``allow_delegation``, the other CLI the
    agent shells out to. Same reasoning as ``_codex_auth_staged_for``: the
    workspace is prepared once, so it is prepared for all of them.
    """
    agents = (phase.agent_config, *((phase.fallback_agent,) if phase.fallback_agent else ()))
    if any(a.allow_delegation for a in agents):
        return frozenset(AgentProvider)
    return frozenset(require_executable_provider(a.provider) for a in agents)


def _append_claude_plugin_dirs(
    claude_cmd: list[str],
    phase: ExecutablePhase,
) -> None:
    # WHY append after command_builder (issue #726, PR2): the entrypoint of
    # the production base image already discovers baked-in plugins under
    # /opt/agentic/plugins/ via AGENTIC_PLUGIN_FLAGS. Per-workflow
    # ``--plugin-dir`` flags are additive: claude CLI accepts multiple
    # ``--plugin-dir`` instances and merges them. Validated against the
    # production image in cycle-004/dogfood-platform-726/validation-experiment.
    for plugin in phase.claude_plugins:
        claude_cmd.append("--plugin-dir")
        claude_cmd.append(f"/workspace/.syn-plugins/{plugin.name}")


def _check_no_conflicting_skill_versions(skills: tuple[ResolvedSkill, ...]) -> None:
    """Reject a phase whose skills contain two different versions of one skill_name.

    WHY (Task 7 review note, issue #772): identity-triple dedup at the
    workflow/phase merge layer means a workflow-level skill declaration and a
    phase-level override could legitimately resolve to two different
    ``resolved_sha`` values for the same ``skill_name``. Both would
    materialize to the same ``.syn-skills/<skill_name>/`` workspace path,
    silently clobbering one version with the other on disk. Fail fast
    instead of letting the last-materialized write win unnoticed.
    """
    seen_sha_by_name: dict[str, str] = {}
    for skill in skills:
        prior_sha = seen_sha_by_name.get(skill.skill_name)
        if prior_sha is not None and prior_sha != skill.resolved_sha:
            raise SkillInstallFailed.not_attempted(
                skill.skill_name,
                f"conflicting versions of skill {skill.skill_name!r}: "
                f"{prior_sha!r} vs {skill.resolved_sha!r}",
            )
        seen_sha_by_name[skill.skill_name] = skill.resolved_sha


_DEADLINE_NOTICE = (
    f"This phase is killed at ${ENV_SYN_PHASE_DEADLINE} (ISO 8601 UTC; read it with "
    f"`echo ${ENV_SYN_PHASE_DEADLINE}`). Only pushed work survives: commit and push before then."
)


async def _setup_secrets(
    workspace: ManagedWorkspace,
    effective_repos: list[str],
    *,
    clone_repos: bool,
    pinned_commits: Sequence[SourceCommit],
    continued_branches: Mapping[str, str] | None,
    include_codex_auth: bool,
    credential_policy: WorkspaceCredentialPolicy,
) -> SetupPhaseSecrets:
    """The ADR-024 setup secrets, or none at all under NoCredentials (#1914).

    NoCredentials resolves no GitHub, Claude or Codex credential, so nothing is
    minted for teardown to revoke. Repos were refused by `admit` before the
    workspace existed.
    """
    from syn_adapters.workspace_backends.service import SetupPhaseSecrets

    if not credential_policy.supplies_credentials:
        return SetupPhaseSecrets(clone_repos=clone_repos)
    return await SetupPhaseSecrets.create(
        repositories=effective_repos,
        clone_repos=clone_repos,
        pinned_commits={c.repository: c.sha for c in pinned_commits if c.sha is not None},
        continued_branches=continued_branches,
        require_github=bool(effective_repos),
        include_codex_auth=include_codex_auth,
        ledger=workspace.issuance_ledger,
    )


class ProvisionResult:
    """Result of workspace provisioning."""

    __slots__ = (
        "agent_env",
        "claude_cmd",
        "command",
        "fallback",
        "workspace",
        "workspace_cm",
    )

    def __init__(
        self,
        workspace: ManagedWorkspace,
        workspace_cm: AbstractAsyncContextManager[ManagedWorkspace],
        agent_env: dict[str, str],
        claude_cmd: list[str],
        command: ProvisionWorkspaceCompletedCommand,
        fallback: FallbackLaunch | None = None,
    ) -> None:
        self.workspace = workspace
        self.fallback = fallback
        self.workspace_cm = workspace_cm  # async context manager for cleanup
        self.agent_env = agent_env
        self.claude_cmd = claude_cmd
        self.command = command


class WorkspaceProvisionHandler:
    """Creates workspace, pre-clones repos, injects context files, builds CLI command.

    Reports ProvisionWorkspaceCompletedCommand.

    ADR-058: repos are cloned during setup phase (not by the agent). After setup,
    synthetic /workspace/AGENTS.md and /workspace/CLAUDE.md are injected so the
    agent starts with full project context from turn 1.
    """

    def __init__(
        self,
        workspace_service: WorkspaceService,
        prompt_builder: PromptBuilder,
        command_builder: CommandBuilder,
        claude_plugin_materializer: ClaudePluginMaterializerProtocol | None = None,
        skill_materializer: SkillMaterializerProtocol | None = None,
    ) -> None:
        self._workspace_service = workspace_service
        self._prompt_builder = prompt_builder
        self._command_builder = command_builder
        # WHY optional (issue #726, PR2): existing tests construct the handler
        # without a materializer, and any phase whose ``claude_plugins`` tuple
        # is empty does not need one. The handler short-circuits the
        # materialization branch when the field is empty, so passing None is
        # safe in those cases.
        self._claude_plugin_materializer = claude_plugin_materializer
        # WHY optional (issue #772): mirrors the plugin materializer above,
        # but unlike plugins, a phase that declares skills with no
        # materializer wired is a hard error (see
        # ``_materialize_and_install_skills``) rather than a silent skip.
        self._skill_materializer = skill_materializer

    async def handle(
        self,
        todo: TodoItem,
        phase: ExecutablePhase,
        workflow_id: str,
        session_id: str,
        repos: list[str] | None = None,
        artifacts: ArtifactCollector | None = None,
        completed_phase_ids: list[str] | None = None,
        phase_outputs: PhaseOutputCache | None = None,
        inputs: dict[str, object] | None = None,
        pinned_commits: Sequence[SourceCommit] = (),
        continued_branches: Mapping[str, str] | None = None,
        eval_id: str | None = None,
    ) -> ProvisionResult:
        """Provision workspace for a phase.

        Args:
            todo: The to-do item being dispatched.
            phase: The executable phase definition.
            workflow_id: Workflow aggregate ID.
            session_id: Agent session ID for this phase.
            repos: Full GitHub URLs to clone and hydrate context from.
            artifacts: Artifact collector for previous-phase injection.
            completed_phase_ids: Phase IDs completed before this one.
            phase_outputs: What each previous phase produced - the primary
                deliverable for prompt substitution, and every file it wrote so
                the previous phases' output TREES can be rebuilt (#988).
            inputs: Workflow execution inputs dict.
            pinned_commits: The commits to check ``repos`` out at instead of
                their default branches' heads - the run's recorded commits, a
                resume's being its parent's (`StartPins.checkout_commits`, #1458).
            continued_branches: ``owner/name`` -> the branch to check a pinned
                repository out ON, at its head, for a phase that continues it
                (`StartPins.checkout_for`, #1513).
            eval_id: The eval the execution belongs to, which bounds what an
                ``eval`` phase's platform token can write (#1744).
        """
        assert todo.phase_id is not None

        outputs = phase_outputs if phase_outputs is not None else PhaseOutputCache()
        effective_repos = repos or []
        # The backend's policy, not the phase, decides whether credentials
        # reach the workspace (#1914). A phase it cannot run is refused here,
        # before any workspace or token exists.
        policy = self._workspace_service.credential_policy
        policy.admit(phase_name=phase.name, repositories=effective_repos)
        workspace_cm = self._workspace_service.create_workspace(
            execution_id=todo.execution_id,
            workflow_id=workflow_id,
            phase_id=todo.phase_id,
            with_sidecar=policy.supplies_credentials,
            inject_tokens=policy.supplies_credentials,
            capture_session_id=session_id,
            platform_access=phase.platform_access,
            eval_id=eval_id,
            resources=phase.resources,
        )

        # Enter the async context manager; clean up on any exception (P0: container leak fix)
        workspace = await workspace_cm.__aenter__()
        try:
            # A command phase runs no agent, so nothing agent-shaped is staged:
            # no model credential, plugin, skill or hook (ADR-078 D3, D7).
            runs_agent = phase.kind is PhaseKind.AGENT
            include_codex_auth = runs_agent and _codex_auth_staged_for(phase)
            await self._hydrate_workspace(
                workspace,
                effective_repos,
                phase_name=phase.name,
                clone_repos=phase.clone_repos,
                pinned_commits=pinned_commits,
                continued_branches=continued_branches,
                include_codex_auth=include_codex_auth,
                credential_policy=policy,
                inline_instructions=runs_agent
                and not all(agent.expands_at_imports for agent in _agents_that_may_run(phase)),
            )
            # Read back BEFORE anything else is staged and long before the agent
            # is launched: a workspace not at its pins is refused here (#967).
            checked_out = (
                await verify_provisioned_checkout(
                    workspace,
                    cloned_pins(effective_repos, pinned_commits),
                    continued_branches=continued_branches or {},
                    phase_name=phase.name,
                )
                if phase.clone_repos
                else ()
            )
            if runs_agent:
                await self._prepare_for_agent(workspace, phase)
            await self._inject_phase_artifacts(
                workspace, artifacts, completed_phase_ids or [], outputs, todo
            )
            return await self._build_provision_result(
                workspace,
                workspace_cm,
                todo,
                phase,
                workflow_id,
                session_id,
                effective_repos,
                outputs.primary,
                inputs,
                checked_out,
            )
        except BaseException as exc:
            await workspace_cm.__aexit__(type(exc), exc, exc.__traceback__)
            raise

    async def _hydrate_workspace(
        self,
        workspace: ManagedWorkspace,
        effective_repos: list[str],
        *,
        phase_name: str,
        clone_repos: bool,
        pinned_commits: Sequence[SourceCommit] = (),
        continued_branches: Mapping[str, str] | None = None,
        include_codex_auth: bool,
        credential_policy: WorkspaceCredentialPolicy,
        inline_instructions: bool,
    ) -> None:
        """Run the secret-injection setup and inject synthetic context files (ADR-058).

        ``inline_instructions`` installs the repo instruction files' content as
        codex's global instructions, for an agent that does not expand
        @-imports (#1835). CLAUDE.md keeps the imports either way.

        ``phase_name`` is here for the failure message alone. The ADR-024 setup
        step runs INSIDE every phase, so "setup failed" on its own points an
        operator at the first workflow phase, a different thing. It was named
        "Prepare the workspace", which caused the confusion; it is now
        "Check the task's premise" (#1298), and the message still
        has to say which setup because the ambiguity was never in the name.

        ``clone_repos=False`` (#1187) still hands the full repo list to
        ``SetupPhaseSecrets``, so the phase keeps its per-repo git credentials
        and its gh hosts.yml entry; only the checkout is skipped. What the
        workspace ends up CONTAINING is the one thing that changes, which is
        why the synthetic context below is derived from it too.
        """
        from syn_adapters.workspace_backends.service import (
            PINNED_COMMIT_UNREACHABLE_EXIT_CODE,
        )

        secrets = await _setup_secrets(
            workspace,
            effective_repos,
            clone_repos=clone_repos,
            pinned_commits=pinned_commits,
            continued_branches=continued_branches,
            include_codex_auth=include_codex_auth,
            credential_policy=credential_policy,
        )
        setup_result = await workspace.run_setup_phase(secrets)
        if setup_result.exit_code != 0:
            detail = describe_process_failure(
                f"Secret-injection setup for phase '{phase_name}'",
                exit_code=setup_result.exit_code,
                output=setup_result.stderr,
                timed_out=setup_result.timed_out,
            )
            if setup_result.timed_out:
                # Not retried in place (see `_run_setup_script`): a killed clone
                # leaves a directory its `[ -d ]` guard would then skip. A resume
                # provisions a fresh workspace, which is the safe retry (PC-126).
                from syn_shared.settings import get_settings

                raise ProvisionStepTimeoutError(
                    ProvisionStep.SECRET_INJECTION,
                    subject=f"phase '{phase_name}'",
                    timeout_seconds=get_settings().setup_phase_timeout_seconds,
                    attempts=1,
                    detail=detail,
                )
            if setup_result.signal_death is not None:
                detail = f"{detail}\n{setup_result.signal_death.describe()}"
            if setup_result.exit_code == PINNED_COMMIT_UNREACHABLE_EXIT_CODE:
                raise PinnedCommitUnreachableError(
                    phase_name=phase_name, detail=detail, exit_code=setup_result.exit_code
                )
            raise NonZeroExitError(detail, exit_code=setup_result.exit_code)
        logger.info("Secret-injection setup completed for phase '%s', secrets cleared", phase_name)

        # Inject synthetic AGENTS.md + CLAUDE.md (ADR-058)
        # CLAUDE.md, which Claude Code reads, is direct @-imports of each repo's
        # distinct instruction files. Direct imports keep repo content at L2 (not
        # L3 via indirection), preserving maximum @import depth for repo-internal
        # context. AGENTS.md is the same file unless an agent that may run here
        # reads it without expanding @-imports (codex, #1835); then the files'
        # content goes to codex's global instructions instead, which every codex
        # launch reads whatever its working directory and size, and AGENTS.md
        # only points there. Claude never reads either, so a fallback or
        # delegation between the two finds its own file already right.
        #
        # Only for repos that are actually ON DISK. Every line of this file is
        # `@/workspace/repos/<name>/...`, so emitting it for a phase that did
        # not clone would point the agent at paths that do not exist.
        cloned_repos = effective_repos if clone_repos else []
        if cloned_repos:
            # Two spellings of one repo (".git", a trailing slash) are one
            # checkout on disk, so its files are imported once, first spelling first.
            names = list(dict.fromkeys(self._repo_name(url) for url in cloned_repos))
            imports = [
                path for name in names for path in await repo_instruction_imports(workspace, name)
            ]
            context = self._generate_workspace_context(imports)
            files = [("AGENTS.md", context.encode()), ("CLAUDE.md", context.encode())]
            if inline_instructions:
                inlined = await inline_instruction_files(
                    workspace, imports, notice=_DEADLINE_NOTICE
                )
                files = [
                    ("AGENTS.md", CODEX_POINTER.encode()),
                    ("CLAUDE.md", context.encode()),
                    (CODEX_INSTRUCTIONS_STAGED, inlined.encode()),
                ]
            await workspace.inject_files(files)
            if inline_instructions:
                await install_codex_instructions(workspace, names)
            logger.info(
                "Injected /workspace/AGENTS.md + CLAUDE.md (%d repo(s), %d import(s))",
                len(cloned_repos),
                len(imports),
            )

    async def _materialize_claude_plugins(
        self,
        workspace: ManagedWorkspace,
        phase: ExecutablePhase,
    ) -> None:
        """Inject resolved claude plugin trees into the workspace (issue #726).

        Runs after secrets clear and the AGENTS.md context inject, so the
        plugin trees land alongside the agent's project context but are
        never visible to the setup script. The orchestrator emits
        ``--plugin-dir`` flags in ``_build_provision_result`` so the agent
        actually loads them.
        """
        if not phase.claude_plugins:
            return
        if self._claude_plugin_materializer is None:
            # WHY warn-instead-of-raise: a workflow that declares plugins but
            # is dispatched through a code path that forgot to wire the
            # materializer should still execute (no plugins is degraded but
            # not broken). Surfaces clearly in logs for the operator.
            logger.warning(
                "Phase %s declared claude_plugins but no materializer is wired; "
                "skipping plugin materialization (issue #726)",
                phase.phase_id,
            )
            return
        plugin_files = await self._claude_plugin_materializer.fetch_for_workspace(
            phase.claude_plugins
        )
        if plugin_files:
            await workspace.inject_files(plugin_files)
            logger.info(
                "Materialized %d claude plugin file(s) across %d plugin(s) into %s",
                len(plugin_files),
                len(phase.claude_plugins),
                workspace.workspace_id,
            )

    async def _materialize_and_install_skills(
        self,
        workspace: ManagedWorkspace,
        phase: ExecutablePhase,
    ) -> None:
        """Inject skill trees and install them for the phase's harness (issue #772).

        Unlike the plugin path, this FAILS FAST: a phase that declares skills
        must get them or must not run. Silent skill-less execution produces
        confusing agent behavior that is worse than a loud provisioning error.
        """
        if not phase.skills:
            return
        _check_no_conflicting_skill_versions(phase.skills)
        if self._skill_materializer is None:
            msg = (
                f"phase {phase.phase_id} declares skills but no skill materializer "
                "is wired; refusing to run the agent without them (issue #772)"
            )
            raise RuntimeError(msg)
        # Resolve the skills-CLI agent key from the phase's provider
        # (claude / codex) - the harness that will actually run.
        agent_selector = phase.agent_config.provider
        agent_key = _SKILLS_CLI_AGENT_KEYS.get(agent_selector)
        if agent_key is None:
            raise SkillInstallFailed.not_attempted(
                phase.skills[0].skill_name,
                f"no skills-cli agent key for agent {agent_selector!r}",
            )
        skill_files = await self._skill_materializer.fetch_for_workspace(phase.skills)
        if skill_files:
            await workspace.inject_files(skill_files)
        for skill in phase.skills:
            await install_skill(
                workspace, skill.skill_name, f"/workspace/.syn-skills/{skill.skill_name}", agent_key
            )
        logger.info(
            "Installed %d skill(s) for agent %s in %s",
            len(phase.skills),
            agent_key,
            workspace.workspace_id,
        )

    async def _inject_phase_artifacts(
        self,
        workspace: ManagedWorkspace,
        artifacts: ArtifactCollector | None,
        completed_ids: list[str],
        outputs: PhaseOutputCache,
        todo: TodoItem,
    ) -> None:
        """Inject artifacts from previous phases into the workspace."""
        if artifacts is not None:
            await artifacts.inject_from_previous_phases_explicit(
                workspace,
                completed_ids,
                outputs.primary,
                execution_id=todo.execution_id,
                phase_files=outputs.files,
            )

    async def _prepare_for_agent(self, workspace: ManagedWorkspace, phase: ExecutablePhase) -> None:
        """Stage what only an agent reads: plugins, skills, the sandbox probe, the hook."""
        await self._materialize_claude_plugins(workspace, phase)
        await self._materialize_and_install_skills(workspace, phase)
        await self._install_baked_delegation_skill(workspace, phase)
        await require_codex_sandbox(workspace, phase)
        await self._install_attribution_hook(workspace)

    async def _build_provision_result(
        self,
        workspace: ManagedWorkspace,
        workspace_cm: AbstractAsyncContextManager[ManagedWorkspace],
        todo: TodoItem,
        phase: ExecutablePhase,
        workflow_id: str,
        session_id: str,
        effective_repos: list[str],
        outputs: dict[str, str],
        inputs: dict[str, object] | None,
        checked_out: Sequence[SourceCommit] = (),
    ) -> ProvisionResult:
        """Build prompt, CLI command, and return the ProvisionResult.

        A command phase gets neither: no prompt, no argv and no agent env,
        so no model credential is ever built for it (ADR-078 D7).
        """
        assert todo.phase_id is not None
        command = ProvisionWorkspaceCompletedCommand(
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            workspace_id=workspace.workspace_id,
            session_id=session_id,
            checked_out_commits=checked_out,
            image_manifest=workspace.image_manifest,
        )
        if phase.kind is PhaseKind.COMMAND:
            return ProvisionResult(
                workspace=workspace,
                workspace_cm=workspace_cm,
                agent_env={},
                claude_cmd=[],
                command=command,
            )
        # repo_url for {{repo_url}} prompt substitution (backward compat — uses first repo)
        repo_url_for_prompt = effective_repos[0] if effective_repos else None
        prompt = await self._prompt_builder(
            phase, todo.execution_id, workflow_id, repo_url_for_prompt, outputs, inputs or {}
        )
        claude_cmd, agent_env = await self._launch_for(
            phase, prompt, workspace, session_id, effective_repos
        )
        fallback: FallbackLaunch | None = None
        if phase.fallback_agent is not None:
            # The SAME prompt, built once: the fallback re-runs this phase, it
            # does not get a phase of its own. Only who runs it changes.
            on_fallback = replace(phase, agent_config=phase.fallback_agent, fallback_agent=None)
            fallback_cmd, fallback_env = await self._launch_for(
                on_fallback, prompt, workspace, session_id, effective_repos
            )
            fallback = FallbackLaunch(
                agent=phase.fallback_agent, agent_env=fallback_env, claude_cmd=fallback_cmd
            )
        return ProvisionResult(
            workspace=workspace,
            workspace_cm=workspace_cm,
            agent_env=agent_env,
            claude_cmd=claude_cmd,
            command=command,
            fallback=fallback,
        )

    async def _launch_for(
        self,
        phase: ExecutablePhase,
        prompt: str,
        workspace: ManagedWorkspace,
        session_id: str,
        effective_repos: list[str],
    ) -> tuple[list[str], dict[str, str]]:
        """The command and env that run ``phase`` on its own ``agent_config``."""
        claude_cmd = self._command_builder(phase, prompt)
        # `--plugin-dir` is a claude-only flag; appending it to a `codex exec`
        # argv (after the prompt) produces an invalid command, so restrict the
        # plugin-dir augmentation to the claude headless path.
        if phase.agent_config.provider != AgentProvider.CODEX:
            _append_claude_plugin_dirs(claude_cmd, phase)

        # Codex authenticates via the injected ~/.codex/auth.json file, NOT the
        # claude env creds; a codex phase must not receive CLAUDE_CODE_OAUTH_TOKEN /
        # ANTHROPIC_API_KEY (cross-provider secret exposure), so it gets an empty
        # agent env.
        _, needs_claude_env = _auth_staging_for(
            phase.agent_config.provider, phase.agent_config.allow_delegation
        )
        agent_env = (
            await build_agent_env(workspace, session_id, self._workspace_service.credential_policy)
            if needs_claude_env
            else {}
        )
        # OUTSIDE the branch above, deliberately. A codex phase gets an empty
        # agent env by design - it authenticates from ~/.codex/auth.json and
        # must not see claude credentials - so `build_agent_env` is the one
        # place repository identity must NOT live: put it there and it reaches
        # claude phases only, leaving every codex phase with the defect this
        # fixes. It is provider-independent, and this is the single point both
        # providers pass through on their way to `workspace.stream(...)`.
        agent_env.update(repo_identity_env(effective_repos))
        return claude_cmd, agent_env

    @staticmethod
    def _repo_name(url: str) -> str:
        """Return repo name from a full GitHub URL.

        Examples:
            "https://github.com/org/repo-a.git" → "repo-a"
            "https://github.com/org/repo-b/"   → "repo-b"
        """
        return url.rstrip("/").split("/")[-1].removesuffix(".git")

    @staticmethod
    async def _install_attribution_hook(workspace: ManagedWorkspace) -> None:
        """Put the operator co-authorship hook where the image's own git config looks.

        The image is meant to carry this. The ``claude-cli`` provider does; the
        ``omni-agent`` provider does not, and its entrypoint skips a missing hook
        source in silence, so on those images every agent commit is authored by
        the bot alone with nothing anywhere saying attribution is off
        (AgentParadise/agentic-primitives#401).

        Installing at provision time makes attribution work on EVERY image,
        including ones built before the hook existed - which is what actually
        makes the feature real, rather than real-once-the-next-image-ships.

        No-op when attribution is not configured. The hook is itself a no-op in
        that case, but writing a file nobody asked for into every workspace is
        worse than not writing it, and the check is one settings read.

        Failures are logged, never raised. A missing trailer is a lost credit; a
        raise here would cost the whole phase. That trade only holds because the
        install is verified - see below - so a silent failure cannot be mistaken
        for success.
        """
        from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_hooks import (
            HOOK_FILENAME,
            WORKSPACE_HOOKS_DIR,
            attribution_hook_source,
        )
        from syn_shared.settings.git_identity import OperatorSettings

        if not OperatorSettings().is_configured:
            return

        target = WORKSPACE_HOOKS_DIR / HOOK_FILENAME
        # inject_files' base_path never reaches the container: copy_to_workspace
        # writes relative to the workspace root and takes no base_path at all
        # (adapter_copy.py:118-133). Passing one is accepted and discarded, which
        # put the hook at /workspace/prepare-commit-msg and left chmod reporting
        # "No such file or directory". So stage inside the workspace, then MOVE
        # it into place with a shell that can create the directory.
        #
        # The staging name is dotted and the move is a `mv`, so nothing is left
        # behind for an agent to notice or accidentally commit.
        staged = ".syn-attribution-hook"
        try:
            await workspace.inject_files([(staged, attribution_hook_source())])
            install = await workspace.execute(
                [
                    "sh",
                    "-c",
                    f"mkdir -p {WORKSPACE_HOOKS_DIR} "
                    f"&& mv /workspace/{staged} {target} "
                    f"&& chmod +x {target}",
                ],
                timeout_seconds=30,
            )
            if install.exit_code != 0:
                logger.warning(
                    "attribution hook could not be installed at %s: %s",
                    target,
                    install.stderr,
                )
                return
            # Assert the effect, not the call. Writing a file and reporting
            # success is how this feature stayed broken for four months, and a
            # hook git cannot execute is ignored in silence.
            check = await workspace.execute(["test", "-x", str(target)], timeout_seconds=30)
            if check.exit_code != 0:
                logger.warning("attribution hook is not present after install at %s", target)
            else:
                logger.info("attribution hook installed at %s", target)
        except Exception as exc:
            logger.warning("attribution hook install failed at %s: %s", target, exc)

    @staticmethod
    async def _install_baked_delegation_skill(
        workspace: ManagedWorkspace, phase: ExecutablePhase
    ) -> None:
        """Install the baked delegation skill for a delegation-enabled phase.

        Rides #772's ``skills add`` seam (harness-agnostic), sourced from the
        image's baked ``delegation`` plugin instead of a registered/materialized
        skill - the base-skill (tier 1) surfacing that #772 plan-1 does not yet
        generalize. ``allow_delegation`` itself only stages both auths (see
        ``_auth_staging_for``); this teaches the primary agent HOW to hand off to
        the other CLI. No-op when the phase does not opt in.
        """
        cfg = phase.agent_config
        if not cfg.allow_delegation:
            return
        # Install the skill teaching the PRIMARY agent to call the OTHER CLI.
        skill_name = _DELEGATION_TARGET_SKILL.get(cfg.provider)
        agent_key = _SKILLS_CLI_AGENT_KEYS.get(cfg.provider)
        if skill_name is None or agent_key is None:
            # allow_delegation is validated headless-only (claude/codex); defensive.
            return
        await install_skill(
            workspace, skill_name, f"{_DELEGATION_SKILL_ROOT}/{skill_name}", agent_key
        )
        logger.info(
            "Installed baked delegation skill %s for agent %s in %s",
            skill_name,
            agent_key,
            workspace.workspace_id,
        )

    @staticmethod
    def _generate_workspace_context(imports: Sequence[str]) -> str:
        """Generate /workspace/CLAUDE.md, and AGENTS.md when every agent expands @-imports.

        The content is a direct @-import of each path in
        ``imports`` (see ``repo_instruction_imports``). Direct imports (not via
        an intermediary file) keep repo content at depth L2, leaving L3-L5 for
        repo-internal imports within Claude Code's 5-level absolute limit.

        AGENTS.md is the Linux Foundation AAIF standard (Dec 2025), loaded by 15+
        platforms. CLAUDE.md is required because Claude Code does not auto-load
        AGENTS.md (issue #6235). Both files ensure full hydration regardless of
        which platform runs the agent.
        """
        lines = [f"@{path}" for path in imports]
        # A pointer, not a time (#1546). This file is written before the
        # phase's clock starts, so a timestamp here would disagree with the
        # one the agent is killed on; the env var is set from that clock.
        lines.append(_DEADLINE_NOTICE)
        return "\n".join(lines) + "\n"
