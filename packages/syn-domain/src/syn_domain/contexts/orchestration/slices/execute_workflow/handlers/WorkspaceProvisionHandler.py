"""WorkspaceProvisionHandler — creates workspace and injects secrets/artifacts (ISS-196).

Extracted from WorkflowExecutionEngine._setup_workspace_for_phase() and
workspace creation (lines 944-958, 1147-1217).

Reports ProvisionWorkspaceCompletedCommand to the aggregate.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

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

_SKIP_URLS = frozenset(
    {
        "https://github.com/placeholder/not-configured",
        "https://github.com/example/repo",
    }
)

# Callable types for dependency injection
PromptBuilder = Callable[
    [ExecutablePhase, str, str, str | None, dict[str, str], dict[str, Any]],
    Awaitable[str],
]
CommandBuilder = Callable[[ExecutablePhase, str], list[str]]


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
    """Creates workspace, injects secrets/artifacts, builds CLI command.

    Reports ProvisionWorkspaceCompletedCommand.
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
        repo_url: str | None,
        artifacts: ArtifactCollector,
        completed_phase_ids: list[str],
        phase_outputs: dict[str, str],
        inputs: dict[str, Any] | None = None,
    ) -> ProvisionResult:
        """Provision workspace for a phase.

        Args:
            todo: The to-do item being processed
            phase: Phase definition
            workflow_id: Workflow ID
            session_id: Session ID for observability
            repo_url: Repository URL (if configured)
            artifacts: Artifact collector for injection
            completed_phase_ids: Previously completed phase IDs
            phase_outputs: Phase output cache for injection

        Returns:
            ProvisionResult with workspace, env, command, and aggregate command
        """
        from syn_adapters.workspace_backends.service import SetupPhaseSecrets

        assert todo.phase_id is not None

        workspace_cm = self._workspace_service.create_workspace(
            execution_id=todo.execution_id,
            workflow_id=workflow_id,
            phase_id=todo.phase_id,
            with_sidecar=True,
            inject_tokens=True,
        )

        # Enter the async context manager
        workspace = await workspace_cm.__aenter__()

        # Parse repo for secrets
        _repo = self._parse_repo(repo_url)

        secrets = await SetupPhaseSecrets.create(
            repository=_repo,
            require_github=_repo is not None,
        )

        setup_result = await workspace.run_setup_phase(secrets)
        if setup_result.exit_code != 0:
            msg = f"Setup phase failed: {setup_result.stderr}"
            raise RuntimeError(msg)
        logger.info("Setup phase completed, secrets cleared")

        # Inject artifacts from previous phases
        await artifacts.inject_from_previous_phases_explicit(
            workspace,
            completed_phase_ids,
            phase_outputs,
            execution_id=todo.execution_id,
        )

        # Build prompt and CLI command
        prompt = await self._prompt_builder(
            phase, todo.execution_id, workflow_id, repo_url, phase_outputs, inputs or {}
        )
        claude_cmd = self._command_builder(phase, prompt)

        # Validate proxy is available — credentials live on the proxy container,
        # not in agent env vars (ISS-43: API key security).
        proxy_url = getattr(workspace, "proxy_url", None)
        if not proxy_url:
            msg = (
                "Shared Envoy proxy not available. "
                "Ensure envoy-proxy service is running and sidecar is enabled."
            )
            raise RuntimeError(msg)

        agent_env: dict[str, str] = {
            ENV_CLAUDE_SESSION_ID: session_id,
            # Route Anthropic SDK calls directly to the Envoy proxy.
            # Do NOT set HTTP_PROXY/HTTPS_PROXY — those cause Node.js to use
            # CONNECT tunneling which Envoy's forward proxy doesn't support.
            # ANTHROPIC_BASE_URL alone redirects the SDK without tunneling (ISS-43).
            ENV_ANTHROPIC_BASE_URL: proxy_url,
            # Placeholder so Claude Code will attempt API calls via OAuth Bearer auth.
            # ANTHROPIC_API_KEY must NOT be set here — if it is, Claude Code uses
            # x-api-key auth and the injected Authorization header is ignored by Anthropic.
            # With only CLAUDE_CODE_OAUTH_TOKEN set, Claude Code sends
            # "Authorization: Bearer proxy-managed", which the Envoy proxy (ext_authz)
            # overwrites with the real token before the request reaches api.anthropic.com (ISS-43).
            ENV_CLAUDE_CODE_OAUTH_TOKEN: "proxy-managed",
        }

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
    def _parse_repo(repo_url: str | None) -> str | None:
        """Parse owner/repo from URL."""
        if not repo_url:
            return None
        normalized = repo_url.rstrip("/")
        if normalized in _SKIP_URLS:
            return None
        parts = normalized.split("/")
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}"
        return None
