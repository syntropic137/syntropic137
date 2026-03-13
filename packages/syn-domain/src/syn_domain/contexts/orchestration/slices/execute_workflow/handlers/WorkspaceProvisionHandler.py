"""WorkspaceProvisionHandler — creates workspace and injects secrets/artifacts (ISS-196).

Extracted from WorkflowExecutionEngine._setup_workspace_for_phase() and
workspace creation (lines 944-958, 1147-1217).

Reports ProvisionWorkspaceCompletedCommand to the aggregate.
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

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from syn_adapters.workspace_backends.service import WorkspaceService
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
        ArtifactCollector,
    )
    from syn_domain.contexts.orchestration.slices.execution_todo.value_objects import (
        TodoItem,
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
    [ExecutablePhase, str, str, str | None, dict[str, str]],
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
            with_sidecar=False,
            inject_tokens=False,
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
            phase, todo.execution_id, workflow_id, repo_url, phase_outputs
        )
        claude_cmd = self._command_builder(phase, prompt)

        # Validate authentication
        if not secrets.claude_code_oauth_token and not secrets.anthropic_api_key:
            msg = (
                "No Claude authentication configured. "
                "Set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY in environment."
            )
            raise RuntimeError(msg)

        agent_env: dict[str, str] = {
            "CLAUDE_SESSION_ID": session_id,
        }
        if secrets.claude_code_oauth_token:
            agent_env["CLAUDE_CODE_OAUTH_TOKEN"] = secrets.claude_code_oauth_token
        if secrets.anthropic_api_key:
            agent_env["ANTHROPIC_API_KEY"] = secrets.anthropic_api_key

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
