"""WorkspaceService - facade for orchestrating workspace lifecycle.

This service composes all workspace adapters and provides a clean interface
for the WorkflowExecutionEngine. It handles the full lifecycle:

1. Create isolation container
2. Start sidecar proxy
3. Vend and inject tokens
4. Execute commands / stream output
5. Collect artifacts
6. Cleanup (destroy container + sidecar)

All operations are event-sourced via WorkspaceAggregate for audit trail.

See ADR-021, ADR-022, ADR-023.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from aef_domain.contexts.workspaces._shared.value_objects import (
    CapabilityType,
    IsolationBackendType,
    IsolationConfig,
    SecurityPolicy,
    SidecarConfig,
    TokenType,
    WorkspaceStatus,
)
from aef_domain.contexts.workspaces._shared.WorkspaceAggregate import WorkspaceAggregate
from aef_domain.contexts.workspaces.create_workspace.CreateWorkspaceCommand import (
    CreateWorkspaceCommand,
)
from aef_domain.contexts.workspaces.terminate_workspace.TerminateWorkspaceCommand import (
    TerminateWorkspaceCommand,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from aef_adapters.workspace_backends.tokens.token_injection_adapter import (
        SidecarTokenInjectionAdapter,
    )
    from aef_domain.contexts.workspaces._shared.ports import (
        EventStreamPort,
        IsolationBackendPort,
        SidecarPort,
    )
    from aef_domain.contexts.workspaces._shared.value_objects import (
        ExecutionResult,
        IsolationHandle,
        SidecarHandle,
        TokenInjectionResult,
    )

logger = logging.getLogger(__name__)


@dataclass
class WorkspaceServiceConfig:
    """Configuration for WorkspaceService.

    Attributes:
        backend: Isolation backend type (docker, gvisor, etc.)
        image: Container image for workspace
        memory_limit_mb: Memory limit in MB
        cpu_limit_cores: CPU limit in cores
        timeout_seconds: Default command timeout
        allowed_hosts: Allowed egress hosts for sidecar
        default_token_ttl: Default token TTL in seconds
    """

    backend: IsolationBackendType = IsolationBackendType.DOCKER_HARDENED
    image: str = "aef-agent-runner:latest"
    memory_limit_mb: int = 512
    cpu_limit_cores: float = 1.0
    timeout_seconds: int = 3600  # 1 hour
    allowed_hosts: tuple[str, ...] = (
        "api.anthropic.com",
        "api.github.com",
        "raw.githubusercontent.com",
    )
    default_token_ttl: int = 300  # 5 minutes
    capabilities: tuple[CapabilityType, ...] = (CapabilityType.NETWORK,)


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

    @property
    def proxy_url(self) -> str | None:
        """Get the proxy URL for HTTP requests."""
        return self.sidecar_handle.proxy_url if self.sidecar_handle else None

    @property
    def status(self) -> WorkspaceStatus:
        """Get current workspace status."""
        return self.aggregate.status


class WorkspaceService:
    """Orchestrates workspace lifecycle with all adapters.

    This is the main entry point for creating and managing workspaces.
    It composes:
    - IsolationBackendPort (container management)
    - SidecarPort (proxy management)
    - TokenInjectionAdapter (token vending + injection)
    - EventStreamPort (stdout streaming)

    Factory methods:
    - create_docker(): Production configuration with Docker
    - create_memory(): Test configuration with mocks

    Usage:
        service = WorkspaceService.create_docker()

        async with service.create_workspace(
            execution_id="exec-123",
            workflow_id="wf-456",
        ) as workspace:
            # Inject tokens
            await workspace.inject_tokens([TokenType.ANTHROPIC])

            # Execute commands
            result = await workspace.execute(["python", "script.py"])

            # Stream agent output
            async for line in workspace.stream(["python", "-u", "agent.py"]):
                event = json.loads(line)
                handle_event(event)
    """

    def __init__(
        self,
        isolation: IsolationBackendPort,
        sidecar: SidecarPort,
        token_injection: SidecarTokenInjectionAdapter,
        event_stream: EventStreamPort,
        config: WorkspaceServiceConfig | None = None,
    ) -> None:
        """Initialize WorkspaceService with adapters.

        Args:
            isolation: Adapter for container management
            sidecar: Adapter for sidecar proxy
            token_injection: Adapter for token injection
            event_stream: Adapter for event streaming
            config: Service configuration
        """
        self._isolation = isolation
        self._sidecar = sidecar
        self._token_injection = token_injection
        self._event_stream = event_stream
        self._config = config or WorkspaceServiceConfig()

    @classmethod
    def create_docker(
        cls,
        config: WorkspaceServiceConfig | None = None,
        token_service: object | None = None,  # TokenVendingService
    ) -> WorkspaceService:
        """Create WorkspaceService with Docker adapters.

        This is the production configuration.

        Args:
            config: Optional service configuration
            token_service: Optional TokenVendingService (uses default if None)

        Returns:
            Configured WorkspaceService
        """
        from aef_adapters.workspace_backends.docker import (
            DockerEventStreamAdapter,
            DockerIsolationAdapter,
            DockerSidecarAdapter,
        )
        from aef_adapters.workspace_backends.tokens import (
            SidecarTokenInjectionAdapter,
            TokenVendingServiceAdapter,
        )
        from aef_tokens.vending import get_token_vending_service

        cfg = config or WorkspaceServiceConfig()

        # Create adapters
        isolation = DockerIsolationAdapter(
            default_image=cfg.image,
            use_gvisor=cfg.backend == IsolationBackendType.GVISOR,
        )
        sidecar = DockerSidecarAdapter()
        event_stream = DockerEventStreamAdapter()

        # Token vending
        tvs = token_service or get_token_vending_service()
        vending = TokenVendingServiceAdapter(tvs)  # type: ignore[arg-type]
        token_injection = SidecarTokenInjectionAdapter(vending, sidecar)

        return cls(
            isolation=isolation,
            sidecar=sidecar,
            token_injection=token_injection,
            event_stream=event_stream,  # type: ignore[arg-type]
            config=cfg,
        )

    @classmethod
    def create_memory(
        cls,
        config: WorkspaceServiceConfig | None = None,
    ) -> WorkspaceService:
        """Create WorkspaceService with in-memory adapters for testing.

        ⚠️  TEST ENVIRONMENT ONLY - will fail in production.

        Args:
            config: Optional service configuration

        Returns:
            Configured WorkspaceService for testing
        """
        from aef_adapters.workspace_backends.memory import (
            MemoryEventStreamAdapter,
            MemoryIsolationAdapter,
            MemorySidecarAdapter,
        )
        from aef_adapters.workspace_backends.tokens import (
            SidecarTokenInjectionAdapter,
            TokenVendingServiceAdapter,
        )
        from aef_tokens.vending import InMemoryTokenStore, TokenVendingService

        cfg = config or WorkspaceServiceConfig()

        # Create memory adapters (will fail if not in test environment)
        isolation = MemoryIsolationAdapter()
        sidecar = MemorySidecarAdapter()
        event_stream = MemoryEventStreamAdapter()

        # In-memory token vending
        store = InMemoryTokenStore()
        tvs = TokenVendingService(store)
        vending = TokenVendingServiceAdapter(tvs)
        token_injection = SidecarTokenInjectionAdapter(vending, sidecar)

        return cls(
            isolation=isolation,
            sidecar=sidecar,
            token_injection=token_injection,
            event_stream=event_stream,  # type: ignore[arg-type]
            config=cfg,
        )

    @asynccontextmanager
    async def create_workspace(
        self,
        execution_id: str,
        workflow_id: str | None = None,
        phase_id: str | None = None,
        *,
        with_sidecar: bool = True,
        inject_tokens: bool = False,
        token_types: list[TokenType] | None = None,
    ) -> AsyncIterator[ManagedWorkspace]:
        """Create a managed workspace with full lifecycle.

        This is an async context manager that:
        1. Creates isolation container
        2. Starts sidecar proxy (if with_sidecar=True)
        3. Optionally injects tokens
        4. Yields ManagedWorkspace for use
        5. Cleans up on exit (destroys container + sidecar)

        Args:
            execution_id: Execution ID for audit trail
            workflow_id: Optional workflow ID
            phase_id: Optional phase ID
            with_sidecar: Whether to start sidecar proxy
            inject_tokens: Whether to inject tokens automatically
            token_types: Token types to inject (if inject_tokens=True)

        Yields:
            ManagedWorkspace for command execution

        Example:
            async with service.create_workspace(
                execution_id="exec-123",
                workflow_id="wf-456",
                inject_tokens=True,
            ) as workspace:
                result = await workspace.execute(["python", "script.py"])
        """
        import uuid

        workspace_id = str(uuid.uuid4())

        # Create aggregate and emit creation event
        aggregate = WorkspaceAggregate()
        create_cmd = CreateWorkspaceCommand(
            aggregate_id=workspace_id,
            execution_id=execution_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            isolation_backend=self._config.backend,
            capabilities=self._config.capabilities,
            image=self._config.image,
        )
        aggregate.create_workspace(create_cmd)

        # Build isolation config
        isolation_config = IsolationConfig(
            execution_id=execution_id,
            workspace_id=workspace_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            backend=self._config.backend,
            capabilities=self._config.capabilities,
            image=self._config.image,
            security_policy=SecurityPolicy(
                memory_limit_mb=self._config.memory_limit_mb,
                cpu_limit_cores=self._config.cpu_limit_cores,
            ),
        )

        isolation_handle: IsolationHandle | None = None
        sidecar_handle: SidecarHandle | None = None

        try:
            # 1. Create isolation container
            logger.info(
                "Creating workspace (id=%s, execution=%s)",
                workspace_id,
                execution_id,
            )
            isolation_handle = await self._isolation.create(isolation_config)
            aggregate.record_isolation_started(
                isolation_id=isolation_handle.isolation_id,
                isolation_type=isolation_handle.isolation_type,
            )

            # 2. Start sidecar if requested
            if with_sidecar:
                sidecar_config = SidecarConfig(
                    workspace_id=workspace_id,
                    listen_port=8080,
                    allowed_hosts=self._config.allowed_hosts,
                )
                sidecar_handle = await self._sidecar.start(
                    sidecar_config,
                    isolation_handle,
                )
                logger.info(
                    "Sidecar started (proxy=%s)",
                    sidecar_handle.proxy_url,
                )

            # 3. Create managed workspace
            workspace = ManagedWorkspace(
                workspace_id=workspace_id,
                execution_id=execution_id,
                aggregate=aggregate,
                isolation_handle=isolation_handle,
                sidecar_handle=sidecar_handle,
                _service=self,
            )

            # 4. Inject tokens if requested
            if inject_tokens and sidecar_handle:
                types = token_types or [TokenType.ANTHROPIC]
                await workspace.inject_tokens(types)

            yield workspace

        except Exception as e:
            # Record error in aggregate
            if aggregate:
                aggregate.record_error(str(e), str(type(e).__name__))
            logger.exception("Workspace error (id=%s): %s", workspace_id, e)
            raise

        finally:
            # 5. Cleanup
            logger.info("Cleaning up workspace (id=%s)", workspace_id)

            # Revoke tokens
            if inject_tokens:
                try:
                    await self._token_injection.revoke(execution_id)
                except Exception as e:
                    logger.warning("Failed to revoke tokens: %s", e)

            # Stop sidecar
            if sidecar_handle:
                try:
                    await self._sidecar.stop(sidecar_handle)
                except Exception as e:
                    logger.warning("Failed to stop sidecar: %s", e)

            # Destroy isolation
            if isolation_handle:
                try:
                    await self._isolation.destroy(isolation_handle)
                except Exception as e:
                    logger.warning("Failed to destroy isolation: %s", e)

            # Emit termination event
            terminate_cmd = TerminateWorkspaceCommand(
                workspace_id=workspace_id,
                reason="Execution completed",
            )
            aggregate.terminate_workspace(terminate_cmd)

            logger.info("Workspace cleaned up (id=%s)", workspace_id)
