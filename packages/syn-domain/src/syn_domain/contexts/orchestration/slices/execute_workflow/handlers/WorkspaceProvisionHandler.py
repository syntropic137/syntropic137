"""WorkspaceProvisionHandler — creates workspace and injects secrets/artifacts (ISS-196).

Extracted from WorkflowExecutionEngine._setup_workspace_for_phase() and
workspace creation (lines 944-958, 1147-1217).

Reports ProvisionWorkspaceCompletedCommand to the aggregate.

ADR-058: Repos are pre-cloned during setup phase. After setup, synthetic
/workspace/AGENTS.md and /workspace/CLAUDE.md are injected with @-imports
of each repo's AGENTS.md and CLAUDE.md, so Claude starts fully hydrated.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.skill_errors import SkillInstallFailed
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ProvisionWorkspaceCompletedCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    WorkspaceMisconfiguredError,
)
from syn_shared.env_constants import (
    ENV_ANTHROPIC_API_KEY,
    ENV_ANTHROPIC_BASE_URL,
    ENV_CLAUDE_CODE_OAUTH_TOKEN,
    ENV_CLAUDE_SESSION_ID,
    ENV_GITHUB_TOKEN,
)

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from typing import Protocol

    from syn_adapters.workspace_backends.service import WorkspaceService
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration._shared.resolved_claude_plugin import (
        ResolvedClaudePlugin,
    )
    from syn_domain.contexts.orchestration._shared.resolved_skill import ResolvedSkill
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
        TodoItem,
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

# Maps our phase agent_id values onto the vercel skills-cli --agent keys.
# The skills CLI (pinned 1.5.14 in the workspace images) owns the per-harness
# install location; we only translate our identifier vocabulary to theirs.
# Verify against `skills add --help` inside the image whenever the pin bumps.
_SKILLS_CLI_AGENT_KEYS: dict[str, str] = {
    "claude": "claude-code",
    "codex": "codex",
    "gemini": "gemini-cli",
}

_SKILL_INSTALL_TIMEOUT_SECONDS = 120

# Callable types for dependency injection
PromptBuilder = Callable[
    [ExecutablePhase, str, str, str | None, dict[str, str], dict[str, object]],
    Awaitable[str],
]
CommandBuilder = Callable[[ExecutablePhase, str], list[str]]


def _is_interactive_phase(workspace: ManagedWorkspace, phase: ExecutablePhase) -> bool:
    """Return whether this phase should dispatch via the interactive-tmux path.

    Explicit signal only: ``phase.agent_config.provider ==
    "claude-interactive"``. The YAML schema has carried an `agent.provider`
    field since PR #765, so `workspace.isolation_handle.isolation_type` is
    no longer consulted as an implicit fallback (issue #771 item 5).

    Raises WorkspaceMisconfiguredError if the phase's declared provider
    and the workspace's actual isolation backend disagree.
    `WorkflowExecutionProcessor._workspace_service_for` is responsible for
    routing `claude-interactive` phases to the interactive-tmux
    WorkspaceService and every other phase to the default one — if that
    routing broke, proceeding here would silently flip which path runs
    (previously masked by the implicit OR) instead of failing loudly.
    """
    explicit_interactive = phase.agent_config.provider == "claude-interactive"
    workspace_is_interactive_tmux = workspace.isolation_handle.isolation_type == "interactive-tmux"
    if explicit_interactive != workspace_is_interactive_tmux:
        msg = (
            f"Phase '{phase.phase_id}' agent_config.provider="
            f"{phase.agent_config.provider!r} but its workspace was provisioned "
            f"with isolation_type={workspace.isolation_handle.isolation_type!r}. "
            "WorkflowExecutionProcessor._workspace_service_for must route "
            "claude-interactive phases to the interactive-tmux WorkspaceService "
            "and all other phases to the default one - this mismatch means that "
            "routing picked the wrong backend for this phase."
        )
        raise WorkspaceMisconfiguredError(msg)
    return explicit_interactive


def _provisioned_agents(phase: ExecutablePhase) -> tuple[str, ...]:
    """Interactive agent name(s) to stage for this phase's workspace.

    For an interactive-tmux phase (`provider == "claude-interactive"`) return
    just the agent the phase drives - `agent_config.agent_id` is the canonical
    claude/codex/gemini name the driver stages auth and launches a pane for.
    Staging only the needed agent avoids the multi-minute cost of copying the
    other two agents' credentials. Returns () for the default docker path
    (which ignores agent selection entirely).
    """
    if phase.agent_config.provider == "claude-interactive":
        return (phase.agent_config.agent_id,)
    return ()


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
            raise SkillInstallFailed(
                skill.skill_name,
                "n/a",
                exit_code=-1,
                stderr=(
                    f"conflicting versions of skill {skill.skill_name!r}: "
                    f"{prior_sha!r} vs {skill.resolved_sha!r}"
                ),
            )
        seen_sha_by_name[skill.skill_name] = skill.resolved_sha


async def _build_agent_env(workspace: ManagedWorkspace, session_id: str) -> dict[str, str]:
    """Build agent environment for workspace execution.

    Injects Claude credentials directly into agent env. ANTHROPIC_BASE_URL
    routes SDK traffic through the Envoy sidecar for observability, but auth
    is carried by the credential env var rather than sidecar substitution.

    See ADR-024 (2026-05-01 update) for why the original "proxy-managed"
    placeholder approach was abandoned and this direct injection was adopted.
    """
    proxy_url = workspace.proxy_url
    if not proxy_url:
        msg = (
            "Shared Envoy proxy not available. "
            "Ensure envoy-proxy service is running and sidecar is enabled."
        )
        raise RuntimeError(msg)

    from syn_shared.settings import get_settings

    settings = get_settings()
    env: dict[str, str] = {
        ENV_CLAUDE_SESSION_ID: session_id,
        ENV_ANTHROPIC_BASE_URL: proxy_url,
    }

    # Prefer OAuth token; fall back to API key. Claude Code CLI v2.1.76+
    # validates credential format locally before sending any HTTP request, so
    # the sidecar-substitution pattern ("proxy-managed" placeholder) no longer
    # works — the CLI rejects it before the proxy gets a chance. ADR-024 updated.
    #
    # TODO(#724): For the API key path specifically, spike whether a syntactically
    # valid placeholder (e.g. "sk-ant-DEADBEEF...") passes the local format check
    # so the Envoy sidecar can substitute the real value on egress. If it works,
    # restore ADR-022/024's "agent never sees raw secrets" invariant for API keys.
    # OAuth is out of scope (ToS gray area for header proxying).
    if settings.claude_code_oauth_token:
        env[ENV_CLAUDE_CODE_OAUTH_TOKEN] = settings.claude_code_oauth_token.get_secret_value()
    elif settings.anthropic_api_key:
        env[ENV_ANTHROPIC_API_KEY] = settings.anthropic_api_key.get_secret_value()
    # No fail-fast here. If neither credential is configured, the workspace
    # agent will exit with "Not logged in" — acceptable for now. A startup-time
    # check that fails the API container with a clear operator message would
    # be cleaner; tracked separately. (Copilot suggested fail-fast in this
    # function, but that breaks smoke tests that exercise the processor loop
    # without configured credentials.)

    # TODO(#723): direct injection — short-term only.
    # TODO(#725): replace with sidecar mint-on-demand to (a) restore the
    # "agent never sees raw secrets" invariant and (b) handle workflows >60min
    # past GitHub's hard 1-hour installation token expiry.
    #
    # Mint a GitHub App installation token and inject as GITHUB_TOKEN so the
    # workspace agent's `gh` CLI can read issues/PRs/comments. Picks the first
    # configured installation (sufficient for single-org dogfood deployments;
    # multi-installation routing belongs in #725's design).
    gh_token = await _resolve_github_app_token()
    if gh_token:
        env[ENV_GITHUB_TOKEN] = gh_token

    return env


async def _resolve_github_app_token() -> str | None:
    """Mint a fresh GitHub App installation token for the agent's first installation.

    Returns None silently if the GitHub App is not configured or no installations
    are reachable — the agent will then fail any `gh` calls with auth errors,
    which is the correct degraded behavior.
    """
    try:
        from syn_adapters.github import GitHubAppClient
        from syn_adapters.github.client_endpoints import list_installations
        from syn_adapters.github.client_token import get_installation_token
        from syn_shared.settings.github import GitHubAppSettings

        github_settings = GitHubAppSettings()
        if not github_settings.is_configured:
            return None

        async with GitHubAppClient(github_settings) as client:
            installations = await list_installations(client)
            if not installations:
                return None
            installation_id = str(installations[0]["id"])
            return await get_installation_token(client, installation_id)
    except Exception as exc:
        logger.warning("Could not mint GitHub App token for agent env: %s", exc)
        return None


class ProvisionResult:
    """Result of workspace provisioning."""

    __slots__ = (
        "agent_env",
        "claude_cmd",
        "command",
        "interactive_prompt",
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
        interactive_prompt: str | None = None,
    ) -> None:
        self.workspace = workspace
        self.workspace_cm = workspace_cm  # async context manager for cleanup
        self.agent_env = agent_env
        self.claude_cmd = claude_cmd
        self.command = command
        # When non-None, AgentExecutionHandler dispatches to the
        # interactive-tmux path (send_message/await_completion/
        # capture_response) instead of workspace.stream(claude_cmd).
        # Populated by WorkspaceProvisionHandler when the phase's
        # agent_config.provider == "claude-interactive".
        self.interactive_prompt = interactive_prompt


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
        phase_outputs: dict[str, str] | None = None,
        inputs: dict[str, object] | None = None,
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
            phase_outputs: Content from previous phase artifacts.
            inputs: Workflow execution inputs dict.
        """
        assert todo.phase_id is not None

        effective_repos = repos or []
        workspace_cm = self._workspace_service.create_workspace(
            execution_id=todo.execution_id,
            workflow_id=workflow_id,
            phase_id=todo.phase_id,
            with_sidecar=True,
            inject_tokens=True,
            agents=_provisioned_agents(phase),
        )

        # Enter the async context manager; clean up on any exception (P0: container leak fix)
        workspace = await workspace_cm.__aenter__()
        try:
            await self._hydrate_workspace(workspace, effective_repos)
            await self._materialize_claude_plugins(workspace, phase)
            await self._materialize_and_install_skills(workspace, phase)
            await self._inject_phase_artifacts(
                workspace, artifacts, completed_phase_ids or [], phase_outputs or {}, todo
            )
            return await self._build_provision_result(
                workspace,
                workspace_cm,
                todo,
                phase,
                workflow_id,
                session_id,
                effective_repos,
                phase_outputs or {},
                inputs,
            )
        except BaseException as exc:
            await workspace_cm.__aexit__(type(exc), exc, exc.__traceback__)
            raise

    async def _hydrate_workspace(
        self,
        workspace: ManagedWorkspace,
        effective_repos: list[str],
    ) -> None:
        """Run setup phase and inject synthetic context files (ADR-058)."""
        from syn_adapters.workspace_backends.service import SetupPhaseSecrets

        secrets = await SetupPhaseSecrets.create(
            repositories=effective_repos,
            require_github=bool(effective_repos),
        )
        setup_result = await workspace.run_setup_phase(secrets)
        if setup_result.exit_code != 0:
            detail = setup_result.stderr or f"exit code {setup_result.exit_code} (no stderr output)"
            msg = f"Setup phase failed: {detail}"
            raise RuntimeError(msg)
        logger.info("Setup phase completed, secrets cleared")

        # Inject synthetic AGENTS.md + CLAUDE.md (ADR-058)
        # Both files are identical: direct @-imports of each repo's AGENTS.md and
        # CLAUDE.md. Direct imports keep repo content at L2 (not L3 via indirection),
        # preserving maximum @import depth for repo-internal context.
        context = self._generate_workspace_context(effective_repos)
        if context:
            await workspace.inject_files(
                [("AGENTS.md", context.encode()), ("CLAUDE.md", context.encode())]
            )
            logger.info(
                "Injected /workspace/AGENTS.md + CLAUDE.md (%d repo(s))", len(effective_repos)
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
        agent_key = _SKILLS_CLI_AGENT_KEYS.get(phase.agent_config.agent_id)
        if agent_key is None:
            raise SkillInstallFailed(
                phase.skills[0].skill_name,
                phase.agent_config.agent_id,
                exit_code=-1,
                stderr=f"no skills-cli agent key for agent_id {phase.agent_config.agent_id!r}",
            )
        skill_files = await self._skill_materializer.fetch_for_workspace(phase.skills)
        if skill_files:
            await workspace.inject_files(skill_files)
        for skill in phase.skills:
            result = await workspace.execute(
                [
                    "skills",
                    "add",
                    f"/workspace/.syn-skills/{skill.skill_name}",
                    "--agent",
                    agent_key,
                    "-y",
                ],
                timeout_seconds=_SKILL_INSTALL_TIMEOUT_SECONDS,
                working_directory="/workspace",
            )
            if result.exit_code != 0:
                raise SkillInstallFailed(
                    skill.skill_name,
                    agent_key,
                    result.exit_code,
                    result.stderr or result.stdout or "",
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
        outputs: dict[str, str],
        todo: TodoItem,
    ) -> None:
        """Inject artifacts from previous phases into the workspace."""
        if artifacts is not None:
            await artifacts.inject_from_previous_phases_explicit(
                workspace, completed_ids, outputs, execution_id=todo.execution_id
            )

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
    ) -> ProvisionResult:
        """Build prompt, CLI command, and return the ProvisionResult."""
        # repo_url for {{repo_url}} prompt substitution (backward compat — uses first repo)
        repo_url_for_prompt = effective_repos[0] if effective_repos else None
        prompt = await self._prompt_builder(
            phase, todo.execution_id, workflow_id, repo_url_for_prompt, outputs, inputs or {}
        )
        # Interactive-tmux dispatch: when the phase declares
        # provider="claude-interactive", AgentExecutionHandler will drive
        # the agent through send_message/await_completion against the
        # tmux pane instead of running claude -p. Skip the CLI command
        # builder (it would produce a noisy claude_cmd we never run) and
        # carry the prompt out-of-band on the ProvisionResult.
        # Interactive detection is explicit-only (issue #771 item 5); see
        # `_is_interactive_phase` for the mismatch guard against the
        # workspace's actual isolation backend.
        is_interactive = _is_interactive_phase(workspace, phase)
        claude_cmd = [] if is_interactive else self._command_builder(phase, prompt)
        interactive_prompt = prompt if is_interactive else None
        if not is_interactive:
            _append_claude_plugin_dirs(claude_cmd, phase)

        # Interactive-tmux runs claude as a TUI with OAuth-on-disk;
        # `_build_agent_env` requires the Envoy proxy URL because the
        # claude -p path needs ANTHROPIC_BASE_URL to route SDK traffic
        # through the sidecar. That sidecar is intentionally absent on
        # this path (see _create_interactive_tmux_impl in
        # WorkspaceService). Skip env build for interactive phases.
        agent_env = {} if is_interactive else await _build_agent_env(workspace, session_id)
        assert todo.phase_id is not None
        command = ProvisionWorkspaceCompletedCommand(
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            workspace_id=workspace.workspace_id,
            session_id=session_id,
        )
        return ProvisionResult(
            workspace=workspace,
            workspace_cm=workspace_cm,
            agent_env=agent_env,
            claude_cmd=claude_cmd,
            command=command,
            interactive_prompt=interactive_prompt,
        )

    async def build_followup_result(
        self,
        todo: TodoItem,
        phase: ExecutablePhase,
        workflow_id: str,
        session_id: str,
        workspace: ManagedWorkspace,
        workspace_cm: AbstractAsyncContextManager[ManagedWorkspace],
        phase_outputs: dict[str, str] | None = None,
        inputs: Mapping[str, object] | None = None,
        repos: list[str] | None = None,
    ) -> ProvisionResult:
        """Build a ProvisionResult for a follow-up phase in a shared workspace.

        Multi-agent (docs/plans/multi-agent-workspaces.md): when the
        execution's first phase already provisioned an
        interactive-tmux workspace, subsequent phases reuse it
        without re-running setup / context injection / artifact
        injection. This method builds only the prompt + per-phase
        ProvisionResult shell.

        ``repos`` is the original execution-scoped repo URL list. It is
        threaded through ONLY for ``{{repo_url}}`` prompt-template
        substitution (see ``_build_provision_result``); workspace
        hydration is still skipped on follow-up phases. Callers that
        already provisioned the workspace in a prior phase should pass
        the same list they passed to ``handle()``.
        """
        return await self._build_provision_result(
            workspace=workspace,
            workspace_cm=workspace_cm,
            todo=todo,
            phase=phase,
            workflow_id=workflow_id,
            session_id=session_id,
            effective_repos=repos or [],
            outputs=phase_outputs or {},
            inputs=dict(inputs) if inputs is not None else None,
        )

    @staticmethod
    def _repo_name(url: str) -> str:
        """Return repo name from a full GitHub URL.

        Examples:
            "https://github.com/org/repo-a.git" → "repo-a"
            "https://github.com/org/repo-b/"   → "repo-b"
        """
        return url.rstrip("/").split("/")[-1].removesuffix(".git")

    @staticmethod
    def _generate_workspace_context(repos: list[str]) -> str:
        """Generate content for both /workspace/CLAUDE.md and /workspace/AGENTS.md.

        Both files receive identical content: direct @-imports of each repo's
        AGENTS.md then CLAUDE.md. Direct imports (not via an intermediary file)
        keep repo content at depth L2, leaving L3-L5 for repo-internal imports
        within Claude Code's 5-level absolute limit. Non-existent files are
        silently ignored by Claude Code's @import system.

        AGENTS.md is the Linux Foundation AAIF standard (Dec 2025), loaded by 15+
        platforms. CLAUDE.md is required because Claude Code does not auto-load
        AGENTS.md (issue #6235). Both files ensure full hydration regardless of
        which platform runs the agent.
        """
        if not repos:
            return ""
        lines: list[str] = []
        for url in repos:
            name = WorkspaceProvisionHandler._repo_name(url)
            lines.append(f"@/workspace/repos/{name}/AGENTS.md")
            lines.append(f"@/workspace/repos/{name}/CLAUDE.md")
        return "\n".join(lines) + "\n"
