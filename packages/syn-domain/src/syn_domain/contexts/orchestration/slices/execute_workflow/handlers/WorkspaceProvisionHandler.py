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

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ProvisionWorkspaceCompletedCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    WorkspaceMisconfiguredError,
)
from syn_shared.agents import AgentProvider
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


logger = logging.getLogger(__name__)

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
    explicit_interactive = phase.agent_config.provider == AgentProvider.CLAUDE_INTERACTIVE
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
    if phase.agent_config.provider == AgentProvider.CLAUDE_INTERACTIVE:
        # `agent_id` now defaults to None (codex-bridge: fixes the
        # provider->agent_id invariant); at the interactive-tmux boundary a
        # pane MUST be named, so coerce a missing agent_id to "claude" here
        # (preserving the pre-existing default) rather than at construction.
        return (phase.agent_config.agent_id or AgentProvider.CLAUDE,)
    return ()


def _auth_staging_for(
    provider: str, allow_delegation: bool, is_interactive: bool
) -> tuple[bool, bool]:
    """Return ``(include_codex_auth, needs_claude_env)`` for a phase.

    Delegation opt-in stages BOTH auths so the primary agent can shell out to
    the other CLI; otherwise auth is scoped to the phase's single provider (the
    codex ``~/.codex/auth.json`` file for codex phases, the claude env
    otherwise). Interactive-tmux never uses the claude sidecar env.
    """
    include_codex_auth = allow_delegation or provider == AgentProvider.CODEX
    needs_claude_env = not is_interactive and (allow_delegation or provider != AgentProvider.CODEX)
    return include_codex_auth, needs_claude_env


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
            include_codex_auth, _ = _auth_staging_for(
                phase.agent_config.provider,
                phase.agent_config.allow_delegation,
                is_interactive=False,
            )
            await self._hydrate_workspace(
                workspace,
                effective_repos,
                include_codex_auth=include_codex_auth,
                delegation_note=self._delegation_note(
                    phase.agent_config.provider, phase.agent_config.allow_delegation
                ),
            )
            await self._materialize_claude_plugins(workspace, phase)
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
        *,
        include_codex_auth: bool,
        delegation_note: str = "",
    ) -> None:
        """Run setup phase and inject synthetic context files (ADR-058)."""
        from syn_adapters.workspace_backends.service import SetupPhaseSecrets

        secrets = await SetupPhaseSecrets.create(
            repositories=effective_repos,
            require_github=bool(effective_repos),
            include_codex_auth=include_codex_auth,
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
        files = self._context_files(effective_repos, delegation_note)
        if files:
            await workspace.inject_files(files)
            logger.info(
                "Injected /workspace/AGENTS.md + CLAUDE.md (%d repo(s), delegation=%s)",
                len(effective_repos),
                bool(delegation_note),
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
        # `--plugin-dir` is a claude-only flag; appending it to a `codex exec`
        # argv (after the prompt) produces an invalid command, so restrict the
        # plugin-dir augmentation to the claude headless path.
        if not is_interactive and phase.agent_config.provider != AgentProvider.CODEX:
            _append_claude_plugin_dirs(claude_cmd, phase)

        # Interactive-tmux runs claude as a TUI with OAuth-on-disk;
        # `_build_agent_env` requires the Envoy proxy URL because the
        # claude -p path needs ANTHROPIC_BASE_URL to route SDK traffic
        # through the sidecar. That sidecar is intentionally absent on
        # this path (see _create_interactive_tmux_impl in
        # WorkspaceService). Skip env build for interactive phases.
        # Codex authenticates via the injected ~/.codex/auth.json file, NOT the
        # claude env creds; a codex phase must not receive CLAUDE_CODE_OAUTH_TOKEN /
        # ANTHROPIC_API_KEY (cross-provider secret exposure), so it gets an empty
        # agent env like the interactive path.
        _, needs_claude_env = _auth_staging_for(
            phase.agent_config.provider,
            phase.agent_config.allow_delegation,
            is_interactive=is_interactive,
        )
        agent_env = await _build_agent_env(workspace, session_id) if needs_claude_env else {}
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
    def _delegation_note(provider: str, allow_delegation: bool) -> str:
        """Delegation recipe for the phase's primary agent, targeting the OTHER
        CLI. Appended to the injected /workspace/CLAUDE.md + AGENTS.md so it
        reaches whichever harness runs (claude auto-loads CLAUDE.md, codex reads
        AGENTS.md) - independent of --plugin-dir / entrypoint plugin discovery.
        """
        if not allow_delegation:
            return ""
        if provider == AgentProvider.CODEX:
            return (
                "\n## Delegation available\n"
                "You may delegate a subtask one-shot to Claude Code (both auths are\n"
                "staged here). Fuller guide: /opt/agentic/plugins/delegation/skills/"
                "delegating-to-claude-p/SKILL.md.\n"
                'Recipe: `claude -p --permission-mode bypassPermissions '
                '--output-format stream-json --verbose "<task>"`.\n'
            )
        # Headless claude primary (provider claude); interactive is rejected at parse.
        return (
            "\n## Delegation available\n"
            "You may delegate a subtask one-shot to OpenAI Codex (both auths are\n"
            "staged here). Fuller guide: /opt/agentic/plugins/delegation/skills/"
            "delegating-to-codex/SKILL.md.\n"
            'Recipe: `codex exec --full-auto --json --skip-git-repo-check "<task>"`.\n'
        )

    @staticmethod
    def _context_files(repos: list[str], delegation_note: str) -> list[tuple[str, bytes]]:
        """Build the (AGENTS.md, CLAUDE.md) inject list, identical content in both.

        Returns an empty list when there is nothing to inject (no repos AND no
        delegation note), which preserves today's behavior. When delegation is
        on but there are no repos, the note alone still injects both files - so
        the recipe reaches the agent even for ``requires_repos: false`` workflows.
        """
        context = WorkspaceProvisionHandler._generate_workspace_context(repos) + delegation_note
        if not context:
            return []
        return [("AGENTS.md", context.encode()), ("CLAUDE.md", context.encode())]

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
