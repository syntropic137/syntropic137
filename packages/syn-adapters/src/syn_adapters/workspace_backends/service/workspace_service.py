"""WorkspaceService - facade for orchestrating workspace lifecycle.

This service composes all workspace adapters and provides a clean interface
for the WorkflowExecutionEngine. It handles the full lifecycle:

1. Create isolation container
2. Run setup script with secrets (ADR-024 Setup Phase)
3. Clear secrets from environment
4. Execute agent commands
5. Collect artifacts
6. Cleanup (destroy container)

All operations are event-sourced via WorkspaceAggregate for audit trail.

See ADR-021, ADR-023, ADR-024.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    CapabilityType,
    IsolationBackendType,
    IsolationConfig,
    SecurityPolicy,
    SidecarConfig,
    TokenType,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.WorkspaceAggregate import (
    WorkspaceAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.CreateWorkspaceCommand import (
    CreateWorkspaceCommand,
)
from syn_domain.contexts.orchestration.domain.commands.TerminateWorkspaceCommand import (
    TerminateWorkspaceCommand,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_adapters.workspace_backends.tokens.token_injection_adapter import (
        SidecarTokenInjectionAdapter,
    )
    from syn_domain.contexts.orchestration._shared.ports import (
        EventStreamPort,
        IsolationBackendPort,
        SidecarPort,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
        SidecarHandle,
    )

logger = logging.getLogger(__name__)


class WorkspaceBackend(Enum):
    """Backend type for workspace isolation.

    Type-safe enum for selecting workspace backend. Use with WorkspaceService.create().

    Backends:
        DOCKER: Production-grade isolation using Docker containers.
                Uses agentic_isolation.WorkspaceDockerProvider with security hardening.

        MEMORY: In-memory mocks for fast unit testing.
                TEST ENVIRONMENT ONLY - will fail if APP_ENVIRONMENT != "test".

        LOCAL: Local filesystem for integration testing without Docker.
               TEST ENVIRONMENT ONLY - will fail if APP_ENVIRONMENT != "test".

    Usage:
        # Production (default)
        service = WorkspaceService.create(backend=WorkspaceBackend.DOCKER)

        # Testing
        service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)
    """

    DOCKER = "docker"
    MEMORY = "memory"
    LOCAL = "local"


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
    image: str = "agentic-workspace-claude-cli:latest"
    memory_limit_mb: int = 2048  # 2GB - Claude CLI needs more memory
    cpu_limit_cores: float = 2.0  # Allow more CPU for agent work
    timeout_seconds: int = 3600  # 1 hour
    allowed_hosts: tuple[str, ...] = (
        "api.anthropic.com",
        "api.github.com",
        "raw.githubusercontent.com",
    )
    default_token_ttl: int = 300  # 5 minutes
    capabilities: tuple[CapabilityType, ...] = (CapabilityType.NETWORK,)
    environment: dict[str, str] = field(default_factory=dict)  # Non-sensitive env vars


class WorkspaceService:
    """Orchestrates workspace lifecycle with all adapters.

    This is the main entry point for creating and managing workspaces.
    It composes:
    - IsolationBackendPort (container management via agentic_isolation)
    - SidecarPort (proxy management)
    - TokenInjectionAdapter (token vending + injection)
    - EventStreamPort (stdout streaming)

    Factory method:
        WorkspaceService.create(backend=WorkspaceBackend.DOCKER)  # Production
        WorkspaceService.create(backend=WorkspaceBackend.MEMORY)  # Testing

    Backends:
        DOCKER: Production-grade isolation using Docker containers
        MEMORY: In-memory mocks (requires APP_ENVIRONMENT=test)
        LOCAL: Local filesystem (requires APP_ENVIRONMENT=test)

    Usage:
        service = WorkspaceService.create()  # Defaults to DOCKER

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
    def create(
        cls,
        backend: WorkspaceBackend = WorkspaceBackend.DOCKER,
        config: WorkspaceServiceConfig | None = None,
        token_service: object | None = None,
        environment: dict[str, str] | None = None,
    ) -> WorkspaceService:
        """Create WorkspaceService with explicit backend selection.

        This is the main factory method. Pass the backend type explicitly
        for type-safe, clear configuration.

        Args:
            backend: Which backend to use (DOCKER, MEMORY, LOCAL).
                     MEMORY and LOCAL only work in test environment.
            config: Optional service configuration
            token_service: Optional TokenVendingService
            environment: Environment variables for containers

        Returns:
            Configured WorkspaceService

        Raises:
            RuntimeError: If MEMORY/LOCAL used outside test environment

        Examples:
            # Production
            service = WorkspaceService.create(backend=WorkspaceBackend.DOCKER)

            # Testing (requires APP_ENVIRONMENT=test)
            service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)
        """
        if backend == WorkspaceBackend.MEMORY:
            return cls._create_memory_impl(config=config)

        if backend == WorkspaceBackend.LOCAL:
            return cls._create_local_impl(config=config)

        # Default: DOCKER
        return cls._create_docker_impl(
            config=config,
            token_service=token_service,
            environment=environment,
        )

    @classmethod
    def _create_docker_impl(
        cls,
        config: WorkspaceServiceConfig | None = None,
        token_service: object | None = None,
        environment: dict[str, str] | None = None,
    ) -> WorkspaceService:
        """Internal: Create WorkspaceService with Docker backend."""
        from agentic_isolation import SecurityConfig

        from syn_adapters.workspace_backends.agentic import (
            AgenticEventStreamAdapter,
            AgenticIsolationAdapter,
        )
        from syn_adapters.workspace_backends.docker import DockerSidecarAdapter
        from syn_adapters.workspace_backends.tokens import (
            SidecarTokenInjectionAdapter,
            TokenVendingServiceAdapter,
        )
        from syn_tokens.vending import get_token_vending_service

        # Build config with environment
        if config:
            cfg = config
            if environment:
                merged_env = dict(cfg.environment)
                merged_env.update(environment)
                cfg = WorkspaceServiceConfig(
                    backend=cfg.backend,
                    image=cfg.image,
                    memory_limit_mb=cfg.memory_limit_mb,
                    cpu_limit_cores=cfg.cpu_limit_cores,
                    timeout_seconds=cfg.timeout_seconds,
                    allowed_hosts=cfg.allowed_hosts,
                    default_token_ttl=cfg.default_token_ttl,
                    capabilities=cfg.capabilities,
                    environment=merged_env,
                )
        else:
            cfg = WorkspaceServiceConfig(environment=environment or {})

        # Choose security profile based on backend type
        # LOCAL is test-only → development(); everything else (DOCKER_HARDENED, GVISOR) → production()
        security = (
            SecurityConfig.development()
            if cfg.backend == IsolationBackendType.LOCAL
            else SecurityConfig.production()
        )

        # Create adapters using agentic_isolation
        isolation = AgenticIsolationAdapter(
            default_image=cfg.image,
            security=security,
        )
        event_stream = AgenticEventStreamAdapter()
        event_stream.set_provider(isolation._provider)

        # Sidecar still uses Docker adapter
        sidecar = DockerSidecarAdapter()

        # Token vending
        tvs = token_service or get_token_vending_service()
        vending = TokenVendingServiceAdapter(tvs)  # type: ignore[arg-type]
        token_injection = SidecarTokenInjectionAdapter(vending, sidecar)

        return cls(
            isolation=isolation,  # type: ignore[arg-type]
            sidecar=sidecar,
            token_injection=token_injection,
            event_stream=event_stream,  # type: ignore[arg-type]
            config=cfg,
        )

    @classmethod
    def _create_memory_impl(
        cls,
        config: WorkspaceServiceConfig | None = None,
    ) -> WorkspaceService:
        """Internal: Create WorkspaceService with memory backend (test only)."""
        from syn_adapters.workspace_backends.memory import (
            MemoryEventStreamAdapter,
            MemoryIsolationAdapter,
            MemorySidecarAdapter,
        )
        from syn_adapters.workspace_backends.tokens import (
            SidecarTokenInjectionAdapter,
            TokenVendingServiceAdapter,
        )
        from syn_tokens.vending import InMemoryTokenStore, TokenVendingService

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

    @classmethod
    def _create_local_impl(
        cls,
        config: WorkspaceServiceConfig | None = None,
    ) -> WorkspaceService:
        """Internal: Create WorkspaceService with local backend (test only)."""
        from syn_shared.settings.environment import check_test_environment

        check_test_environment()  # Raises if not test

        # TODO: Implement using agentic_isolation.WorkspaceLocalProvider
        # For now, fall back to memory
        logger.warning("LOCAL backend not fully implemented, using MEMORY")
        return cls._create_memory_impl(config=config)

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
        extra_environment: dict[str, str] | None = None,
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
            extra_environment: Additional environment variables to inject
                (e.g., OTel configuration for observability)

        Yields:
            ManagedWorkspace for command execution

        Example:
            async with service.create_workspace(
                execution_id="exec-123",
                workflow_id="wf-456",
                inject_tokens=True,
                extra_environment={"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317"},
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

        # Build isolation config with merged environment
        merged_environment = dict(self._config.environment or {})
        if extra_environment:
            merged_environment.update(extra_environment)

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
            environment=merged_environment,
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
