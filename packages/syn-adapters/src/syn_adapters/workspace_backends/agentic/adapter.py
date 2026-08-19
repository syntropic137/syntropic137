"""Agentic workspace adapters - thin wrappers around agentic_isolation.

These adapters implement Syn137's domain ports by delegating to the
agentic_isolation library from agentic-primitives. This keeps Syn137
focused on orchestration and observability, not container management.

See ADR-021: Isolated Workspace Architecture
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from agentic_isolation import (
    SecurityConfig,
    WorkspaceDockerProvider,
)

from syn_adapters.workspace_backends.agentic.adapter_copy import (
    check_workspace_health,
    copy_files_from_workspace,
    copy_files_to_workspace,
)
from syn_adapters.workspace_backends.agentic.session_store_env import (
    apply_session_store_env,
    deployment_identity,
)

# Re-exported for backward compatibility (issue #771 item 7): the canonical
# definition moved to `syn_adapters.workspace_backends.errors` so other
# backends (interactive-tmux) can raise/import it without depending on this
# Docker-specific module. Existing `from ...agentic.adapter import
# WorkspaceProvisionError` call sites keep working unchanged.
from syn_adapters.workspace_backends.errors import WorkspaceProvisionError
from syn_adapters.workspace_backends.image_verification import verify_image_async
from syn_shared.env_constants import (
    ENV_SYN_AGENT_NETWORK,
    ENV_SYN_WORKSPACE_CONTAINER_DIR,
    ENV_SYN_WORKSPACE_HOST_DIR,
)
from syn_shared.settings.workspace_images import DEFAULT_WORKSPACE_IMAGE

if TYPE_CHECKING:
    from agentic_isolation import AgenticWorkspace

    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
        IsolationConfig,
        IsolationHandle,
    )
    from syn_shared.settings.session_store import SessionStoreSettings

logger = logging.getLogger(__name__)

__all__ = ["AgenticIsolationAdapter", "WorkspaceProvisionError"]


class AgenticIsolationAdapter:
    """Implements IsolationBackendPort using agentic_isolation.

    This adapter delegates container lifecycle management to the
    WorkspaceDockerProvider from agentic-primitives.

    Usage:
        adapter = AgenticIsolationAdapter()
        handle = await adapter.create(config)
        result = await adapter.execute(handle, ["python", "script.py"])
        await adapter.destroy(handle)
    """

    def __init__(
        self,
        *,
        default_image: str = DEFAULT_WORKSPACE_IMAGE,
        security: SecurityConfig | None = None,
        workspace_container_dir: str | None = None,
        workspace_host_dir: str | None = None,
        session_store: SessionStoreSettings | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            default_image: Default Docker image for workspaces
            security: Security configuration (defaults to production)
            workspace_container_dir: Path inside orchestrator container (for file I/O)
            workspace_host_dir: Path on Docker host (for volume mounts)
            session_store: Central session-store settings. Defaults to
                ``get_settings().session_store``, which is DISABLED unless
                ``SYN_SESSION_STORE_URL`` is configured.

        When running inside a container, both paths are needed:
        - container_dir: where this process writes files (/workspaces)
        - host_dir: what Docker uses for -v mount (host absolute path)

        Uses env vars SYN_WORKSPACE_CONTAINER_DIR and SYN_WORKSPACE_HOST_DIR if not set.
        """

        self._default_image = default_image
        self._security = security or SecurityConfig.production()

        # Central session store (SeshMagic). Resolved from the settings object
        # rather than os.environ so the credential stays a SecretStr all the way
        # to the point of injection. Disabled by default — see
        # `session_store_env.build_session_store_env`.
        if session_store is None:
            from syn_shared.settings import get_settings

            session_store = get_settings().session_store
        self._session_store = session_store

        # Get paths from env or args
        container_dir = workspace_container_dir or os.environ.get(
            ENV_SYN_WORKSPACE_CONTAINER_DIR, "/workspaces"
        )
        host_dir = workspace_host_dir or os.environ.get(ENV_SYN_WORKSPACE_HOST_DIR)

        self._container_base_dir = container_dir
        self._host_base_dir = host_dir  # May be None if same as container dir

        # ISS-43: Use agent-net so containers can reach the shared Envoy proxy
        # but cannot reach the internet directly.
        agent_network = os.environ.get(ENV_SYN_AGENT_NETWORK, "agent-net")

        self._provider = WorkspaceDockerProvider(
            default_image=default_image,
            security=self._security,
            workspace_base_dir=container_dir,
            workspace_host_dir=host_dir,  # For Docker volume mounts
            default_network=agent_network,
        )
        self._workspaces: dict[str, AgenticWorkspace] = {}

    @staticmethod
    def is_available() -> bool:
        """Check if Docker is available."""
        return WorkspaceDockerProvider.is_available()

    def _build_environment(self, config: IsolationConfig) -> dict[str, str]:
        """Build the container environment, including the session-store block."""
        # Central session-store capture (SeshMagic). The capability lives in the
        # workspace image and activates purely from these variables; Syn137 only
        # supplies the contract.
        #
        # OPT-IN, DEFAULT OFF: when no store URL is configured this STRIPS the
        # six reserved AGENTIC_SESSION_STORE_* keys and adds nothing, so a
        # self-hoster with no SeshMagic instance gets a container environment
        # byte-identical to before this integration existed — including when a
        # caller passes those keys itself via `extra_environment`. The opt-in
        # switch must not be defeatable from the public workspace API.
        #
        # When enabled the adapter's values win over any caller-supplied value of
        # the same name: URL, token, partition and tags are derived from host
        # settings and THIS execution, and must not be redirectable or spoofable
        # by a phase's environment block.
        #
        # SPOOL is container-local (/spool), deliberately NOT a mounted volume.
        # Tradeoff: if the container is SIGKILLed before finalize runs, that
        # session is lost. This is not a regression — today nothing is captured
        # at all. A persistent volume would fix it but drags in volume lifecycle
        # management that nobody has designed yet, so it is a deliberate
        # follow-up rather than an omission.
        return apply_session_store_env(
            config.environment or {},
            self._session_store,
            execution_id=config.execution_id,
            workspace_id=config.workspace_id,
            workflow_id=config.workflow_id,
            phase_id=config.phase_id,
            # Which Syn137 deployment produced this session. Without it every
            # workspace across dev, beta and prod is indistinguishable in the
            # corpus: the envelope's own origin.environment is the runtime
            # CLASS, which is the same value for all of them.
            deployment=self._deployment_identity(),
        )

    @staticmethod
    def _deployment_identity() -> str:
        """``syntropic137__<app_environment>`` for this deployment.

        Imported locally, matching how session-store settings are resolved above:
        syn_shared settings resolve 1Password at first construction, so importing
        at module scope would make that a side effect of importing the adapter.
        """
        from syn_shared.settings import get_settings

        return deployment_identity(str(get_settings().app_environment))

    async def create(self, config: IsolationConfig) -> IsolationHandle:
        """Create an isolated workspace container.

        Args:
            config: Isolation configuration from Syn137 domain

        Returns:
            IsolationHandle for subsequent operations
        """
        from agentic_isolation import WorkspaceConfig

        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            IsolationHandle,
        )

        environment = self._build_environment(config)

        # Map Syn137 config to agentic_isolation config
        # ISS-43: Network is set on the provider (default_network in __init__),
        # not on WorkspaceConfig. Containers join agent-net to reach the shared
        # Envoy proxy but cannot reach the internet directly.
        #
        # NOTE: the session-store write token is in `environment` only. It must
        # never be copied into `labels` — labels are readable by anyone who can
        # run `docker inspect`.
        image = config.image or self._default_image

        # Supply-chain gate: verify the cosign signature of the exact image
        # reference we are about to run, before any container exists. Raises
        # ImageVerificationError (a WorkspaceProvisionError) on failure, so an
        # unverified image never reaches the provider.
        #
        # The RETURN VALUE is what runs, not `image`. For a digest-pinned
        # registry reference they are the same string; for an explicitly
        # permitted local image the return value is that image's immutable
        # local image ID, so Docker cannot pull or retag something else in
        # between. See image_verification for the full policy.
        image = await verify_image_async(image)

        ws_config = WorkspaceConfig(
            provider="docker",
            image=image,
            working_dir="/workspace",
            environment=environment,
            labels={
                "syn.execution_id": config.execution_id,
                "syn.workspace_id": config.workspace_id,
            },
            security=self._security,
        )

        # Create workspace via provider — wrap so docker/network failures surface
        # with execution context all the way to the CLI (was "Unknown error").
        try:
            workspace_obj = await self._provider.create(ws_config)
        except Exception as exc:
            logger.exception(
                "Workspace provisioning failed (execution=%s, workspace=%s)",
                config.execution_id,
                config.workspace_id,
            )
            raise WorkspaceProvisionError(
                f"Workspace provisioning failed for execution {config.execution_id}: {exc}"
            ) from exc

        # Store for later operations
        self._workspaces[workspace_obj.id] = workspace_obj  # type: ignore[arg-type]  # Workspace vs AgenticWorkspace adapter boundary

        logger.info(
            "Created workspace (id=%s, execution=%s)",
            workspace_obj.id,
            config.execution_id,
        )

        return IsolationHandle(
            isolation_id=workspace_obj.id,
            isolation_type="docker",
            proxy_url=None,
            workspace_path="/workspace",
            host_workspace_path=workspace_obj.metadata.get("workspace_dir", ""),
        )

    async def destroy(self, handle: IsolationHandle) -> None:
        """Destroy an isolated workspace.

        Args:
            handle: Handle from create()
        """
        workspace = self._workspaces.pop(handle.isolation_id, None)
        if workspace is None:
            logger.warning("Workspace not found: %s", handle.isolation_id)
            return

        logger.info("Destroying workspace (id=%s)", handle.isolation_id)
        await self._provider.destroy(workspace)  # type: ignore[arg-type]  # Workspace vs AgenticWorkspace adapter boundary

    async def execute(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Execute command in workspace.

        Args:
            handle: Handle from create()
            command: Command to execute
            timeout_seconds: Max execution time
            working_directory: Working directory override
            environment: Additional environment variables

        Returns:
            ExecutionResult with exit code, stdout, stderr
        """
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            ExecutionResult,
        )

        workspace = self._workspaces.get(handle.isolation_id)
        if workspace is None:
            return ExecutionResult(
                exit_code=1,
                success=False,
                duration_ms=0.0,
                stderr="Workspace not found",
            )

        # Join command list into shell command
        cmd_str = " ".join(command)

        result = await self._provider.execute(
            workspace,  # type: ignore[arg-type]  # Workspace vs AgenticWorkspace adapter boundary
            cmd_str,
            timeout=float(timeout_seconds) if timeout_seconds else None,
            cwd=working_directory,
            env=environment,
        )

        return ExecutionResult(
            exit_code=result.exit_code,
            success=result.success,
            duration_ms=result.duration_ms,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=result.timed_out,
        )

    async def health_check(self, handle: IsolationHandle) -> bool:
        """Check if workspace is healthy."""
        return check_workspace_health(self._workspaces, handle)

    async def copy_to(
        self,
        handle: IsolationHandle,
        files: list[tuple[str, bytes]],
        base_path: str = "/workspace",
    ) -> None:
        """Copy files into workspace."""
        await copy_files_to_workspace(self._workspaces, self._provider, handle, files, base_path)

    async def copy_from(
        self,
        handle: IsolationHandle,
        patterns: list[str],
        base_path: str = "/workspace",
    ) -> list[tuple[str, bytes]]:
        """Copy files from workspace via mounted volume."""
        return await copy_files_from_workspace(handle, patterns, base_path)
