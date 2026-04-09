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
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ProvisionWorkspaceCompletedCommand,
)
from syn_shared.env_constants import (
    ENV_ANTHROPIC_BASE_URL,
    ENV_CLAUDE_CODE_OAUTH_TOKEN,
    ENV_CLAUDE_SESSION_ID,
)

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from syn_adapters.workspace_backends.service import WorkspaceService
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
        TodoItem,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
        ArtifactCollector,
    )

logger = logging.getLogger(__name__)

# Callable types for dependency injection
PromptBuilder = Callable[
    [ExecutablePhase, str, str, str | None, dict[str, str], dict[str, object]],
    Awaitable[str],
]
CommandBuilder = Callable[[ExecutablePhase, str], list[str]]


def _build_agent_env(workspace: ManagedWorkspace, session_id: str) -> dict[str, str]:
    """Build agent environment with proxy-based auth (ISS-43).

    Validates proxy is available (credentials live on the proxy container,
    not in agent env vars). Routes Anthropic SDK via ANTHROPIC_BASE_URL
    (not HTTP_PROXY — Node.js CONNECT tunneling breaks Envoy forward proxy).
    """
    proxy_url = getattr(workspace, "proxy_url", None)
    if not proxy_url:
        msg = (
            "Shared Envoy proxy not available. "
            "Ensure envoy-proxy service is running and sidecar is enabled."
        )
        raise RuntimeError(msg)
    return {
        ENV_CLAUDE_SESSION_ID: session_id,
        ENV_ANTHROPIC_BASE_URL: proxy_url,
        ENV_CLAUDE_CODE_OAUTH_TOKEN: "proxy-managed",
    }


class ProvisionResult:
    """Result of workspace provisioning."""

    __slots__ = ("agent_env", "claude_cmd", "command", "workspace", "workspace_cm")

    def __init__(
        self,
        workspace: ManagedWorkspace,
        workspace_cm: AbstractAsyncContextManager[ManagedWorkspace],
        agent_env: dict[str, str],
        claude_cmd: list[str],
        command: ProvisionWorkspaceCompletedCommand,
    ) -> None:
        self.workspace = workspace
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
    ) -> None:
        self._workspace_service = workspace_service
        self._prompt_builder = prompt_builder
        self._command_builder = command_builder

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
        from syn_adapters.workspace_backends.service import SetupPhaseSecrets

        assert todo.phase_id is not None

        effective_repos = repos or []
        completed_ids = completed_phase_ids or []
        outputs = phase_outputs or {}

        workspace_cm = self._workspace_service.create_workspace(
            execution_id=todo.execution_id,
            workflow_id=workflow_id,
            phase_id=todo.phase_id,
            with_sidecar=True,
            inject_tokens=True,
        )

        # Enter the async context manager
        workspace = await workspace_cm.__aenter__()

        secrets = await SetupPhaseSecrets.create(
            repositories=effective_repos,
            require_github=bool(effective_repos),
        )

        setup_result = await workspace.run_setup_phase(secrets)
        if setup_result.exit_code != 0:
            msg = f"Setup phase failed: {setup_result.stderr}"
            raise RuntimeError(msg)
        logger.info("Setup phase completed, secrets cleared")

        # Inject synthetic AGENTS.md + CLAUDE.md (ADR-058)
        # Both files are identical: direct @-imports of each repo's AGENTS.md and
        # CLAUDE.md. Direct imports keep repo content at L2 (not L3 via indirection),
        # preserving maximum @import depth for repo-internal context.
        context = self._generate_workspace_context(effective_repos)
        if context:
            await workspace.inject_files(
                [
                    ("AGENTS.md", context.encode()),
                    ("CLAUDE.md", context.encode()),
                ]
            )
            logger.info(
                "Injected /workspace/AGENTS.md + CLAUDE.md (%d repo(s))", len(effective_repos)
            )

        # Inject artifacts from previous phases
        if artifacts is not None:
            await artifacts.inject_from_previous_phases_explicit(
                workspace,
                completed_ids,
                outputs,
                execution_id=todo.execution_id,
            )

        # repo_url for {{repo_url}} prompt substitution (backward compat — uses first repo)
        repo_url_for_prompt = effective_repos[0] if effective_repos else None

        # Build prompt and CLI command
        prompt = await self._prompt_builder(
            phase, todo.execution_id, workflow_id, repo_url_for_prompt, outputs, inputs or {}
        )
        claude_cmd = self._command_builder(phase, prompt)

        agent_env = _build_agent_env(workspace, session_id)

        workspace_id = getattr(workspace, "id", todo.phase_id)

        command = ProvisionWorkspaceCompletedCommand(
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            workspace_id=str(workspace_id),
            session_id=session_id,
        )

        return ProvisionResult(
            workspace=workspace,
            workspace_cm=workspace_cm,
            agent_env=agent_env,
            claude_cmd=claude_cmd,
            command=command,
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
