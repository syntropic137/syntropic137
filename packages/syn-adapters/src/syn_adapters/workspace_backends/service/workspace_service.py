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
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_adapters.workspace_backends.service.workspace_lifecycle import (
    build_isolation_config,
    cleanup_workspace,
    create_workspace_aggregate,
    provision_workspace,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    CapabilityType,
    IsolationBackendType,
    TokenType,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from agentic_events import Recording

    from syn_adapters.workspace_backends.tokens.token_injection_adapter import (
        SidecarTokenInjectionAdapter,
    )
    from syn_domain.contexts.orchestration._shared.ports import (
        EventStreamPort,
        IsolationBackendPort,
        SidecarPort,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationConfig,
        IsolationHandle,
        SidecarHandle,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.WorkspaceAggregate import (
        WorkspaceAggregate,
    )

logger = logging.getLogger(__name__)


class WorkspaceBackend(Enum):
    """Backend type for workspace isolation.

    DOCKER: Production-grade Docker containers.
    MEMORY/LOCAL: Test-only mocks (requires APP_ENVIRONMENT=test).
    RECORDING: Replay pre-recorded sessions for offline testing.
    """

    DOCKER = "docker"
    MEMORY = "memory"
    LOCAL = "local"
    RECORDING = "recording"


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

    Composes IsolationBackendPort, SidecarPort, TokenInjectionAdapter,
    and EventStreamPort into a single facade.

    Usage:
        service = WorkspaceService.create()  # Defaults to DOCKER
        async with service.create_workspace(execution_id="exec-123") as workspace:
            result = await workspace.execute(["python", "script.py"])
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
        from syn_adapters.workspace_backends.docker import SharedEnvoyAdapter
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

        # Shared Envoy proxy for credential injection (ISS-43).
        # Agents never see API keys — the proxy injects them via ext_authz.
        proxy_url = os.environ.get("SYN_PROXY_URL", "http://syn-envoy-proxy:8081")
        sidecar = SharedEnvoyAdapter(proxy_url=proxy_url)

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
        token_injection = SidecarTokenInjectionAdapter(vending, sidecar)  # type: ignore[arg-type]  # MemorySidecarAdapter satisfies SidecarPort protocol

        return cls(
            isolation=isolation,
            sidecar=sidecar,  # type: ignore[arg-type]  # MemorySidecarAdapter satisfies SidecarPort protocol
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

    @classmethod
    def create_recording(
        cls,
        recording: Recording | str | Path,
        *,
        config: WorkspaceServiceConfig | None = None,
    ) -> WorkspaceService:
        """Create WorkspaceService that replays a pre-recorded session.

        ⚠️ TEST ENVIRONMENT ONLY ⚠️

        Uses RecordingEventStreamAdapter for the event stream while keeping
        all other adapters as in-memory mocks.

        Args:
            recording: Recording enum, task name string, or path to recording.
            config: Optional service configuration.

        Returns:
            Configured WorkspaceService with recording-backed event stream.

        Examples:
            from agentic_events import Recording
            service = WorkspaceService.create_recording(Recording.SIMPLE_BASH)

            async with service.create_workspace(execution_id="test") as ws:
                async for line in ws.stream(["claude", "-p", "test"]):
                    process_event(line)
        """
        from syn_adapters.workspace_backends.memory import (
            MemoryIsolationAdapter,
            MemorySidecarAdapter,
        )
        from syn_adapters.workspace_backends.recording import RecordingEventStreamAdapter
        from syn_adapters.workspace_backends.tokens import (
            SidecarTokenInjectionAdapter,
            TokenVendingServiceAdapter,
        )
        from syn_tokens.vending import InMemoryTokenStore, TokenVendingService

        cfg = config or WorkspaceServiceConfig()

        isolation = MemoryIsolationAdapter()
        sidecar = MemorySidecarAdapter()
        event_stream = RecordingEventStreamAdapter(recording)

        store = InMemoryTokenStore()
        tvs = TokenVendingService(store)
        vending = TokenVendingServiceAdapter(tvs)
        token_injection = SidecarTokenInjectionAdapter(vending, sidecar)  # type: ignore[arg-type]  # MemorySidecarAdapter satisfies SidecarPort protocol

        return cls(
            isolation=isolation,
            sidecar=sidecar,  # type: ignore[arg-type]  # MemorySidecarAdapter satisfies SidecarPort protocol
            token_injection=token_injection,
            event_stream=event_stream,  # type: ignore[arg-type]
            config=cfg,
        )

    def _build_workspace_aggregate_and_config(
        self,
        workspace_id: str,
        execution_id: str,
        workflow_id: str | None,
        phase_id: str | None,
        extra_environment: dict[str, str] | None,
    ) -> tuple[WorkspaceAggregate, IsolationConfig]:
        """Create aggregate and isolation config for a new workspace.

        Args:
            workspace_id: Unique workspace ID
            execution_id: Execution ID for audit trail
            workflow_id: Optional workflow ID
            phase_id: Optional phase ID
            extra_environment: Additional environment variables

        Returns:
            Tuple of (WorkspaceAggregate, IsolationConfig).
        """
        aggregate = create_workspace_aggregate(
            workspace_id=workspace_id,
            execution_id=execution_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            backend=self._config.backend,
            capabilities=self._config.capabilities,
            image=self._config.image,
        )

        isolation_config = build_isolation_config(
            config=self._config,
            workspace_id=workspace_id,
            execution_id=execution_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            extra_environment=extra_environment,
        )

        return aggregate, isolation_config

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

        Creates isolation container, optional sidecar proxy, injects tokens,
        yields ManagedWorkspace, and cleans up on exit.

        Args:
            execution_id: Execution ID for audit trail
            workflow_id: Optional workflow ID
            phase_id: Optional phase ID
            with_sidecar: Whether to start sidecar proxy
            inject_tokens: Whether to inject tokens automatically
            token_types: Token types to inject (if inject_tokens=True)
            extra_environment: Additional environment variables

        Yields:
            ManagedWorkspace for command execution
        """
        import uuid

        workspace_id = str(uuid.uuid4())

        aggregate, isolation_config = self._build_workspace_aggregate_and_config(
            workspace_id, execution_id, workflow_id, phase_id, extra_environment,
        )

        isolation_handle: IsolationHandle | None = None
        sidecar_handle: SidecarHandle | None = None

        try:
            isolation_handle, sidecar_handle = await provision_workspace(
                self, isolation_config, aggregate, workspace_id,
                with_sidecar=with_sidecar,
            )

            workspace = ManagedWorkspace(
                workspace_id=workspace_id,
                execution_id=execution_id,
                aggregate=aggregate,
                isolation_handle=isolation_handle,
                sidecar_handle=sidecar_handle,
                _service=self,
            )

            if inject_tokens and sidecar_handle:
                types = token_types or [TokenType.ANTHROPIC]
                await workspace.inject_tokens(types)

            yield workspace

        except Exception as e:
            if aggregate:
                aggregate.record_error(str(e), str(type(e).__name__))
            logger.exception("Workspace error (id=%s): %s", workspace_id, e)
            raise

        finally:
            await cleanup_workspace(
                self, aggregate, workspace_id, execution_id,
                isolation_handle=isolation_handle,
                sidecar_handle=sidecar_handle,
                inject_tokens=inject_tokens,
            )
