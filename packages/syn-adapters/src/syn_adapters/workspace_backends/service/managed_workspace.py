"""ManagedWorkspace - a managed workspace with all resources attached.

This module contains the ManagedWorkspace dataclass returned by
WorkspaceService.create_workspace(). It provides a simple interface
for executing commands and streaming output in an isolated workspace.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    TokenType,
    WorkspaceStatus,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from syn_adapters.workspace_backends.service.workspace_service import WorkspaceService
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
        IsolationHandle,
        SidecarHandle,
        TokenInjectionResult,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.WorkspaceAggregate import (
        WorkspaceAggregate,
    )

from syn_adapters.workspace_backends.service.setup_phase_secrets import (
    DEFAULT_SETUP_SCRIPT,
    SetupPhaseSecrets,
)

logger = logging.getLogger(__name__)


@dataclass
class ManagedWorkspace:
    """A managed workspace with all resources attached.

    This is returned by WorkspaceService.create_workspace() and provides
    a simple interface for executing commands and streaming output.

    The workspace is automatically cleaned up when exiting the context manager.
    """

    workspace_id: str
    execution_id: str
    aggregate: WorkspaceAggregate
    isolation_handle: IsolationHandle
    sidecar_handle: SidecarHandle | None
    _service: WorkspaceService = field(repr=False)
    _tokens_injected: bool = False

    @property
    def path(self) -> Path:
        """Get the workspace path for agents running on the host.

        This returns the HOST path (mounted into the container) so that
        agents like claude-agent-sdk can access files locally. The same
        files will be visible inside the container at /workspace.

        For commands that need to run INSIDE the container, use
        execute() which runs via docker exec.
        """
        from pathlib import Path

        # Prefer host path for local agent execution (claude-agent-sdk runs on host)
        if self.isolation_handle.host_workspace_path:
            return Path(self.isolation_handle.host_workspace_path)
        # Fallback to container path (for in-container execution)
        if self.isolation_handle.workspace_path:
            return Path(self.isolation_handle.workspace_path)
        # Last resort fallback
        return Path(f"/tmp/syn-workspace-{self.execution_id}")

    async def execute(
        self,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Execute a command in the workspace.

        Args:
            command: Command to execute
            timeout_seconds: Override timeout
            working_directory: Override working directory
            environment: Additional environment variables

        Returns:
            ExecutionResult with exit code, stdout, stderr
        """
        return await self._service._isolation.execute(
            self.isolation_handle,
            command,
            timeout_seconds=timeout_seconds,
            working_directory=working_directory,
            environment=environment,
        )

    async def stream(
        self,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        """Stream stdout from a command.

        Args:
            command: Command to execute
            timeout_seconds: Override timeout
            working_directory: Override working directory
            environment: Additional environment variables

        Yields:
            Individual stdout lines
        """
        stream = self._service._event_stream.stream(
            self.isolation_handle,
            command,
            timeout_seconds=timeout_seconds,
            working_directory=working_directory,
            environment=environment,
        )
        async for line in stream:  # type: ignore[attr-defined]
            yield line

    @property
    def last_stream_exit_code(self) -> int | None:
        """Exit code from the most recent stream() call.

        Returns None if no stream has completed yet.
        """
        return self._service._event_stream.last_exit_code

    async def inject_tokens(
        self,
        token_types: list[TokenType] | None = None,
        ttl_seconds: int | None = None,
    ) -> TokenInjectionResult:
        """Inject tokens into the workspace via sidecar.

        Args:
            token_types: Token types to inject (default: ANTHROPIC)
            ttl_seconds: Token TTL (default: from config)

        Returns:
            TokenInjectionResult
        """
        if self.sidecar_handle is None:
            raise RuntimeError("No sidecar - cannot inject tokens")

        types = token_types or [TokenType.ANTHROPIC]
        ttl = ttl_seconds or self._service._config.default_token_ttl

        result = await self._service._token_injection.inject(
            self.isolation_handle,
            execution_id=self.execution_id,
            token_types=types,
            sidecar_handle=self.sidecar_handle,
            ttl_seconds=ttl,
        )

        self._tokens_injected = True
        return result

    async def inject_files(
        self,
        files: list[tuple[str, bytes]],
        base_path: str = "/workspace",
    ) -> None:
        """Inject files into the workspace.

        Args:
            files: List of (relative_path, content) tuples
            base_path: Base path in workspace
        """
        await self._service._isolation.copy_to(
            self.isolation_handle,
            files,
            base_path=base_path,
        )

    async def collect_files(
        self,
        patterns: list[str] | None = None,
        base_path: str = "/workspace",
    ) -> list[tuple[str, bytes]]:
        """Collect files from the workspace.

        Args:
            patterns: Glob patterns (default: ["artifacts/**/*"])
            base_path: Base path in workspace

        Returns:
            List of (relative_path, content) tuples
        """
        pats = patterns or ["artifacts/**/*"]
        return await self._service._isolation.copy_from(
            self.isolation_handle,
            pats,
            base_path=base_path,
        )

    async def run_setup_phase(
        self,
        secrets: SetupPhaseSecrets,
        setup_script: str | None = None,
    ) -> ExecutionResult:
        """Run setup phase with secrets, then clear secrets (ADR-024).

        This method:
        1. Runs the setup script with secrets available as env vars
        2. Clears all secrets from the container environment
        3. Removes any temporary files that might contain secrets

        After this method completes, the agent phase can safely run
        without access to raw secrets.

        Args:
            secrets: Secrets to make available during setup
            setup_script: Custom setup script (uses DEFAULT_SETUP_SCRIPT if None)

        Returns:
            ExecutionResult from setup script
        """
        # Build environment with secrets
        # Uses explicit env var names for clarity (no GH_TOKEN ambiguity)
        setup_env: dict[str, str] = {}

        if secrets.github_app_token:
            # GITHUB_APP_TOKEN is the only supported GitHub auth method
            setup_env["GITHUB_APP_TOKEN"] = secrets.github_app_token

        if secrets.claude_code_oauth_token:
            setup_env["CLAUDE_CODE_OAUTH_TOKEN"] = secrets.claude_code_oauth_token

        if secrets.anthropic_api_key:
            setup_env["ANTHROPIC_API_KEY"] = secrets.anthropic_api_key

        # Git identity from GitHub App bot configuration
        if secrets.git_author_name:
            setup_env["GIT_AUTHOR_NAME"] = secrets.git_author_name
            setup_env["GIT_COMMITTER_NAME"] = secrets.git_author_name
        if secrets.git_author_email:
            setup_env["GIT_AUTHOR_EMAIL"] = secrets.git_author_email
            setup_env["GIT_COMMITTER_EMAIL"] = secrets.git_author_email

        # Write setup script to container
        script = setup_script or DEFAULT_SETUP_SCRIPT
        await self.inject_files(
            [(".setup/setup.sh", script.encode())],
            base_path="/workspace",
        )

        # Run setup script WITH secrets
        logger.info("Running setup phase with secrets (workspace=%s)", self.workspace_id)
        result = await self.execute(
            ["bash", "/workspace/.setup/setup.sh"],
            environment=setup_env,
            timeout_seconds=60,  # Setup should be quick
        )

        if result.exit_code != 0:
            logger.error(
                "Setup phase failed (exit=%d): %s",
                result.exit_code,
                result.stderr,
            )
            return result

        # Clear secrets from environment
        await self._clear_secrets()

        logger.info("Setup phase complete, secrets cleared (workspace=%s)", self.workspace_id)
        return result

    async def _clear_secrets(self) -> None:
        """Clear all traces of secrets from the container.

        This is called after setup phase completes. It removes:
        - Environment variables containing secrets
        - Shell history
        - Temporary files

        Note: Git credentials in ~/.git-credentials are intentionally kept
        so the agent can push without raw token access.
        """
        # Clear shell history and temp files
        clear_script = """#!/bin/bash
# Clear shell history
rm -f ~/.bash_history ~/.zsh_history /root/.bash_history /root/.zsh_history 2>/dev/null || true

# Clear setup script (contains no secrets, but clean up)
rm -rf /workspace/.setup 2>/dev/null || true

# Clear any temp files
rm -rf /tmp/secrets* /tmp/setup* 2>/dev/null || true

# Note: ~/.git-credentials is kept intentionally for git push
"""
        await self.inject_files(
            [(".cleanup/clear.sh", clear_script.encode())],
            base_path="/workspace",
        )
        await self.execute(
            ["bash", "/workspace/.cleanup/clear.sh"],
            timeout_seconds=10,
        )

        # Clean up the cleanup script too
        await self.execute(
            ["rm", "-rf", "/workspace/.cleanup"],
            timeout_seconds=5,
        )

    async def interrupt(self) -> bool:
        """Send SIGINT to the Claude CLI process inside the container.

        Uses docker exec to find and signal the claude process:
            docker exec <container> sh -c "kill -INT $(pgrep -n claude)"

        Returns True if signal was delivered successfully. Non-fatal on failure
        so cleanup can continue even if the process is already gone.
        """
        import asyncio

        container_id = getattr(self.isolation_handle, "container_id", None)
        if not container_id:
            logger.warning("interrupt(): no container_id on isolation handle, skipping SIGINT")
            return False

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "exec",
                container_id,
                "sh",
                "-c",
                "kill -INT $(pgrep -n claude) 2>/dev/null || true",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5.0)
            success = proc.returncode == 0
            if success:
                logger.info("interrupt(): SIGINT delivered to claude process in %s", container_id)
            else:
                logger.warning(
                    "interrupt(): SIGINT failed (exit=%d) for container %s",
                    proc.returncode,
                    container_id,
                )
            return success
        except Exception as e:
            logger.warning("interrupt(): failed to send SIGINT to %s: %s", container_id, e)
            return False

    @property
    def proxy_url(self) -> str | None:
        """Get the proxy URL for HTTP requests."""
        return self.sidecar_handle.proxy_url if self.sidecar_handle else None

    @property
    def status(self) -> WorkspaceStatus:
        """Get current workspace status."""
        return self.aggregate.status
