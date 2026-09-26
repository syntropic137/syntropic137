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

    from syn_adapters.workspace_backends.service.setup_phase_secrets import (
        SetupPhaseSecrets,
    )
    from syn_adapters.workspace_backends.service.workspace_service import WorkspaceService
    from syn_domain.contexts.agent_sessions import RolloutDocument
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
        IsolationHandle,
        SidecarHandle,
        TokenInjectionResult,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.WorkspaceAggregate import (
        WorkspaceAggregate,
    )

from syn_adapters.workspace_backends.service.codex_rollout import read_codex_rollout
from syn_adapters.workspace_backends.service.git_credential_renewal import (
    CredentialSource,
)
from syn_adapters.workspace_backends.service.git_credential_renewal import (
    renew_git_credential as _renew_git_credential,
)
from syn_adapters.workspace_backends.service.managed_workspace_ops import (
    interrupt_container,
)
from syn_adapters.workspace_backends.service.setup_phase import (
    clear_secrets,
)
from syn_adapters.workspace_backends.service.setup_phase import (
    run_setup_phase as _run_setup_phase,
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
    #: How this workspace's git credential was minted, recorded by the setup
    #: phase so it can be minted AGAIN later (#1393). None until the setup
    #: phase has run, and for a workspace with no repositories at all, which
    #: has no credential to renew.
    _credential_source: CredentialSource | None = None

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
        wrapper_name: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream stdout from a command.

        Args:
            command: Command to execute
            timeout_seconds: Override timeout
            working_directory: Override working directory
            environment: Additional environment variables
            wrapper_name: The ``$0`` a transport that really creates a process
                announces itself under, from ``AgentLaunchEvidence.wrapper_name``.
                None when the caller is not collecting launch evidence.

        Yields:
            Individual stdout lines
        """
        stream = self._service._event_stream.stream(
            self.isolation_handle,
            command,
            timeout_seconds=timeout_seconds,
            working_directory=working_directory,
            environment=environment,
            wrapper_name=wrapper_name,
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

        Delegates to setup_phase.run_setup_phase(). See that module for details.

        Args:
            secrets: Secrets to make available during setup
            setup_script: Custom setup script (uses DEFAULT_SETUP_SCRIPT if None)

        Returns:
            ExecutionResult from setup script
        """
        # Remembered BEFORE the run, and from the secrets rather than from the
        # caller: this object is what `renew_git_credential` re-mints from, and
        # a copy of the answers taken anywhere else could disagree with the
        # credential actually installed here (#1393).
        self._credential_source = CredentialSource(
            repositories=tuple(secrets.repositories), can_open_pr=secrets.can_open_pr
        )
        return await _run_setup_phase(self, secrets, setup_script)

    async def renew_git_credential(self) -> None:
        """Replace this container's git credential with a freshly minted one.

        Satisfies the domain's ``GitWorkspace``. Lives on the workspace because
        the credential does: it is a file inside THIS container, and the token
        in it is scoped to the repositories THIS workspace was provisioned
        with. See `git_credential_renewal` for why it expires before the
        container does.

        Raises:
            CredentialRenewalFailedError: the credential is not known to be
                usable. A workspace whose setup phase never ran holds no
                credential to renew and returns quietly instead - nothing
                downstream of it can be depending on one.
        """
        if self._credential_source is None:
            return
        await _renew_git_credential(self, self._credential_source)

    async def _clear_secrets(self) -> None:
        """Clear all traces of secrets from the container.

        Delegates to setup_phase.clear_secrets(). See that module for details.
        """
        await clear_secrets(self)

    async def codex_rollout(self, native_session_id: str) -> RolloutDocument | None:
        """The rollout codex wrote for this session, or None if it cannot be read.

        Satisfies ``CodexRolloutPort``. Lives on the workspace because the file
        is INSIDE this container and outlives nothing: once the workspace is
        torn down the only copy of what model codex ran is gone (#1284).

        Delegates to codex_rollout.read_codex_rollout(). See that module for
        why the codex layout is not restated there.
        """
        return await read_codex_rollout(self, native_session_id)

    async def interrupt(self) -> bool:
        """Send SIGINT to the Claude CLI process inside the container.

        Uses docker exec to find and signal the claude process:
            docker exec <container> sh -c "kill -INT $(pgrep -n claude)"

        Returns True if signal was delivered successfully. Non-fatal on failure
        so cleanup can continue even if the process is already gone.
        """
        return await interrupt_container(self.isolation_handle)

    @property
    def proxy_url(self) -> str | None:
        """Get the proxy URL for HTTP requests."""
        return self.sidecar_handle.proxy_url if self.sidecar_handle else None

    @property
    def status(self) -> WorkspaceStatus:
        """Get current workspace status."""
        return self.aggregate.status
