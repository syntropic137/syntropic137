"""ManagedWorkspace - a managed workspace with all resources attached.

This module contains the ManagedWorkspace dataclass returned by
WorkspaceService.create_workspace(). It provides a simple interface
for executing commands and streaming output in an isolated workspace.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    TokenType,
    WorkspaceStatus,
)
from syn_shared.env_constants import ENV_SYN_PHASE_DEADLINE

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable
    from contextlib import AbstractAsyncContextManager
    from pathlib import Path

    from syn_adapters.platform_access import WorkspacePlatformGrant
    from syn_adapters.workspace_backends.service.credential_keeper import CredentialLapse
    from syn_adapters.workspace_backends.service.issued_tokens import IssuedToken
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
        WorkspaceUsage,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.WorkspaceAggregate import (
        WorkspaceAggregate,
    )

from syn_adapters.workspace_backends.service.codex_rollout import read_codex_rollout
from syn_adapters.workspace_backends.service.credential_keeper import keep_credential_fresh
from syn_adapters.workspace_backends.service.git_credential_renewal import (
    CredentialSource,
)
from syn_adapters.workspace_backends.service.git_credential_renewal import (
    renew_git_credential as _renew_git_credential,
)
from syn_adapters.workspace_backends.service.issued_tokens import IssuanceLedger
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
    #: Every GitHub token minted for this workspace, by any path (#725). What
    #: the renewal task reads the installed credential's expiry from, and what
    #: teardown revokes. In-process only - see `issued_tokens`.
    _ledger: IssuanceLedger = field(default_factory=IssuanceLedger, repr=False)
    #: What the isolation consumed, set by teardown (`create_workspace`'s
    #: `finally`) and so only readable after `__aexit__`. None before teardown,
    #: and when the backend measured nothing.
    teardown_usage: WorkspaceUsage | None = None
    #: This phase's read-only access to the Syntropic137 API (ADR-072), set by
    #: `create_workspace` and revoked by its teardown. None while platform
    #: access is OFF, which is the default.
    platform_grant: WorkspacePlatformGrant | None = field(default=None, repr=False)

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
        # The agent's read-only API access (ADR-072) rides on every streamed
        # launch, whatever the provider: callers do not need to know it exists.
        if self.platform_grant is not None:
            await self._bound_platform_grant_to_phase(environment)
            environment = {**(environment or {}), **self.platform_grant.env}
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

    async def _bound_platform_grant_to_phase(self, environment: dict[str, str] | None) -> None:
        """The API token expires with the phase, not only when teardown revokes it."""
        deadline = (environment or {}).get(ENV_SYN_PHASE_DEADLINE)
        tokens = self._service._platform_tokens
        if deadline is None or tokens is None or self.platform_grant is None:
            return
        await tokens.bound_to_deadline(self.platform_grant.token, datetime.fromisoformat(deadline))

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
        self._credential_source = CredentialSource(repositories=tuple(secrets.repositories))
        # `secrets.issued` is already in the ledger: `SetupPhaseSecrets.create`
        # recorded each token as it was minted (#725).
        result = await _run_setup_phase(self, secrets, setup_script)
        if result.exit_code == 0:
            self._ledger.installed(secrets.issued)
        return result

    @property
    def credential_expires_at(self) -> datetime | None:
        """When the GitHub credential in this container expires, or None if it has none."""
        return self._ledger.credential_expires_at

    @property
    def issued_tokens(self) -> tuple[IssuedToken, ...]:
        """Every GitHub token minted for this workspace so far, oldest first."""
        return self._ledger.issued

    @property
    def issuance_ledger(self) -> IssuanceLedger:
        """Where a token minted for this workspace is recorded the moment it exists.

        Handed to `SetupPhaseSecrets.create` so no failure between minting and
        installing can strand a live token outside teardown's reach (#725).
        """
        return self._ledger

    def keep_git_credential_fresh(
        self, *, on_lapse: Callable[[CredentialLapse], Awaitable[None]]
    ) -> AbstractAsyncContextManager[None]:
        """Renew this workspace's credential on schedule while the block runs (#725).

        Enter it as the agent starts and leave it as the agent stops; see
        `credential_keeper` for the schedule and what ``on_lapse`` is told.
        """
        return keep_credential_fresh(self, on_lapse=on_lapse)

    async def revoke_issued_credentials(self) -> None:
        """Revoke every unexpired GitHub token minted for this workspace. Never raises.

        For teardown, and only once nothing in the container can still need a
        token: after the quarantine push. `WorkspaceService.create_workspace`
        calls it on exit, which every phase path reaches after its guard has
        run. Best effort across a crash - see `issued_tokens`.
        """
        if not self._ledger.issued:
            return
        try:
            from syn_adapters.github import GitHubAppClient
            from syn_shared.settings.github import GitHubAppSettings

            async with GitHubAppClient(GitHubAppSettings()) as client:
                await self._ledger.revoke_unexpired(client.revoke_installation_token)
        except Exception:
            logger.exception(
                "Could not revoke the GitHub tokens issued to workspace %s; they stay "
                "usable until they expire, at most an hour from issue.",
                self.workspace_id,
            )

    async def renew_git_credential(self) -> tuple[IssuedToken, ...]:
        """Replace this container's git credential with a freshly minted one.

        Satisfies the domain's ``GitWorkspace``. Lives on the workspace because
        the credential does: it is a file inside THIS container, and the token
        in it is scoped to the repositories THIS workspace was provisioned
        with. See `git_credential_renewal` for why it expires before the
        container does.

        Returns:
            The tokens it issued and installed, also recorded in this
            workspace's ledger. Empty when there was nothing to renew.

        Raises:
            CredentialRenewalFailedError: the credential is not known to be
                usable. A workspace whose setup phase never ran holds no
                credential to renew and returns quietly instead - nothing
                downstream of it can be depending on one.
        """
        if self._credential_source is None:
            return ()
        return await _renew_git_credential(self, self._credential_source, self._ledger)

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
