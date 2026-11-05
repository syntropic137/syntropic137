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

import dataclasses
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_adapters.workspace_backends.service.workspace_lifecycle import (
    ProvisionTrack,
    build_isolation_config,
    cleanup_workspace,
    create_workspace_aggregate,
    finish_abandoned_create,
    provision_workspace,
)
from syn_domain.contexts.orchestration import (
    HOST_CREDENTIALS,
    WorkspaceCredentialPolicy,
    WorkspaceResourceRequest,
    require_memory_within_cap,
    require_pids_within_cap,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    CapabilityType,
    IsolationBackendType,
    TokenType,
)
from syn_shared.platform_access import PlatformScope
from syn_shared.settings.workspace import (
    DEFAULT_WORKSPACE_CPU_LIMIT,
    DEFAULT_WORKSPACE_MEMORY_LIMIT_MB,
    DEFAULT_WORKSPACE_PIDS_LIMIT,
    WorkspaceRuntime,
)
from syn_shared.settings.workspace_images import DEFAULT_WORKSPACE_IMAGE

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from agentic_events import Recording
    from agentic_isolation.providers.e2b_client import E2BSandboxClient

    from syn_adapters.platform_access import PlatformTokenService
    from syn_adapters.workspace_backends.service.memory_ledger import (
        LedgerReservation,
        WorkspaceMemoryLedger,
    )
    from syn_adapters.workspace_backends.service.workspace_lifecycle import IsolationTeardown
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
    from syn_shared.settings.e2b import E2BSettings
    from syn_shared.settings.workspace import WorkspaceSettings

logger = logging.getLogger(__name__)


class WorkspaceBackend(Enum):
    """Backend type for workspace isolation.

    DOCKER: Production-grade Docker containers.
    E2B: E2B cloud sandboxes, only when SYN_E2B_ENABLED is set (#1915, dark).
    MEMORY/LOCAL: Test-only mocks (requires APP_ENVIRONMENT=test).
    RECORDING: Replay pre-recorded sessions for offline testing.
    """

    DOCKER = "docker"
    E2B = "e2b"
    MEMORY = "memory"
    LOCAL = "local"
    RECORDING = "recording"

    @classmethod
    def selected(cls, e2b: E2BSettings) -> WorkspaceBackend:
        """The production backend: E2B when the operator turned it on, else Docker.

        ``E2BSettings`` refuses to load when enabled without a key or template,
        so an enabled flag here always has what E2B needs; there is no fallback.
        """
        return cls.E2B if e2b.enabled else cls.DOCKER


@dataclass
class WorkspaceServiceConfig:
    """Configuration for WorkspaceService.

    Attributes:
        backend: Isolation backend type (docker, gvisor, etc.)
        image: Container image for workspace
        memory_limit_mb: Memory limit in MB for a phase that requests none
        memory_max_mb: The most memory a phase may request (okrs-51p.30)
        pids_limit: Processes and threads for a phase that requests none
        pids_max: The highest pids limit a phase may request (okrs-51p.30)
        cpu_limit_cores: CPU limit in cores
        timeout_seconds: Default command timeout
        allowed_hosts: Allowed egress hosts for sidecar
        default_token_ttl: Default token TTL in seconds
    """

    backend: IsolationBackendType = IsolationBackendType.DOCKER_HARDENED
    image: str = DEFAULT_WORKSPACE_IMAGE
    memory_limit_mb: int = DEFAULT_WORKSPACE_MEMORY_LIMIT_MB
    memory_max_mb: int = DEFAULT_WORKSPACE_MEMORY_LIMIT_MB
    pids_limit: int = DEFAULT_WORKSPACE_PIDS_LIMIT
    pids_max: int = DEFAULT_WORKSPACE_PIDS_LIMIT
    cpu_limit_cores: float = DEFAULT_WORKSPACE_CPU_LIMIT
    timeout_seconds: int = 3600  # 1 hour
    allowed_hosts: tuple[str, ...] = (
        "api.anthropic.com",
        "api.github.com",
        "raw.githubusercontent.com",
    )
    default_token_ttl: int = 300  # 5 minutes
    capabilities: tuple[CapabilityType, ...] = (CapabilityType.NETWORK,)
    environment: dict[str, str] = field(default_factory=dict)  # Non-sensitive env vars
    #: OCI runtime to request from agentic-workspace. None = its auto mode.
    runtime: WorkspaceRuntime | None = None

    @classmethod
    def from_settings(cls, settings: WorkspaceSettings) -> WorkspaceServiceConfig:
        """The configuration an operator asked for via SYN_WORKSPACE_*."""
        return cls(
            image=settings.docker_image,
            memory_limit_mb=settings.memory_limit_mb,
            # Unset is "no phase may ask for more than the default".
            memory_max_mb=(
                settings.memory_limit_mb
                if settings.memory_max_mb is None
                else settings.memory_max_mb
            ),
            pids_limit=settings.pids_limit,
            # Unset is "no phase may ask for more than the default".
            pids_max=(settings.pids_limit if settings.pids_max is None else settings.pids_max),
            cpu_limit_cores=settings.cpu_limit,
            runtime=settings.runtime,
        )


def _not_shown_gone(
    track: ProvisionTrack,
    isolation_handle: IsolationHandle | None,
    teardown: IsolationTeardown | None,
) -> str | None:
    """Why this workspace's container cannot be shown gone, or None when it can.

    Only a clean teardown of a NAMED container is proof. A create that never
    started made nothing. A create that raised or was abandoned names nothing,
    yet the backend may have made a container and failed to remove it, so the
    memory reconciler decides from a listing (Codex on #2148).
    """
    if isolation_handle is None:
        if track.create_task is None:
            return None
        if track.still_creating():
            return "create was abandoned while running"
        return "create named no container"
    if teardown is None:
        return "teardown was interrupted"
    if teardown.failure is not None:
        return f"teardown failed: {teardown.failure.kind}: {teardown.failure.message}"
    return None


def _nothing() -> None:
    pass


def _refuse_credentials_under(
    policy: WorkspaceCredentialPolicy, with_sidecar: bool, inject_tokens: bool
) -> None:
    """A credential-free (NoCredentials) workspace takes no sidecar and no tokens (#1914)."""
    if not policy.supplies_credentials and (with_sidecar or inject_tokens):
        msg = (
            "A credential-free (NoCredentials) workspace takes no sidecar and no "
            f"injected tokens (with_sidecar={with_sidecar}, inject_tokens={inject_tokens})"
        )
        raise ValueError(msg)


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
        credential_policy: WorkspaceCredentialPolicy = HOST_CREDENTIALS,
    ) -> None:
        """Initialize WorkspaceService with adapters.

        Args:
            isolation: Adapter for container management
            sidecar: Adapter for sidecar proxy
            token_injection: Adapter for token injection
            event_stream: Adapter for event streaming
            config: Service configuration
            credential_policy: Whether host credentials reach its workspaces
                (#1914). The Docker factory takes it from the BackendKit.
        """
        self._isolation = isolation
        self._credential_policy = credential_policy
        self._sidecar = sidecar
        self._token_injection = token_injection
        self._event_stream = event_stream
        self._config = config or WorkspaceServiceConfig()
        #: Mints each workspace's read-only API token (ADR-072). None, or a
        #: disabled service, means workspaces get no token at all.
        self._platform_tokens: PlatformTokenService | None = None
        #: Where every workspace of this PROCESS reserves its memory, so a
        #: large one counts as more than one run (okrs-51p.30). None: no
        #: accounting, which only tests and the memory backend use.
        self._memory_ledger: WorkspaceMemoryLedger | None = None

    @property
    def credential_policy(self) -> WorkspaceCredentialPolicy:
        """Whether host credentials reach this service's workspaces (#1914)."""
        return self._credential_policy

    @classmethod
    def create(
        cls,
        backend: WorkspaceBackend = WorkspaceBackend.DOCKER,
        config: WorkspaceServiceConfig | None = None,
        token_service: object | None = None,
        environment: dict[str, str] | None = None,
        capture_source_instance_id: str | None = None,
        platform_tokens: PlatformTokenService | None = None,
        credential_policy: WorkspaceCredentialPolicy = HOST_CREDENTIALS,
        e2b: E2BSettings | None = None,
        e2b_client: E2BSandboxClient | None = None,
        memory_ledger: WorkspaceMemoryLedger | None = None,
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
            platform_tokens: Issues each workspace's read-only API token (ADR-072)
            credential_policy: HostCredentials (today's behaviour) or
                NoCredentials, fixed for every workspace this service makes (#1914)
            e2b: E2B settings, required for E2B and ignored otherwise (#1915).
                E2B is always NoCredentials, whatever ``credential_policy`` says.
            e2b_client: The E2B sandbox client; the e2b SDK adapter, keyed
                from ``e2b.api_key``, when omitted. Tests pass a double.
            memory_ledger: The process-wide workspace memory ledger
                (okrs-51p.30). Shared across every service in the process,
                so production passes the one singleton.

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
            service = cls._create_memory_impl(config=config, credential_policy=credential_policy)
        elif backend == WorkspaceBackend.LOCAL:
            service = cls._create_local_impl(config=config)
        elif backend == WorkspaceBackend.E2B:
            if e2b is None:
                msg = "WorkspaceBackend.E2B needs its E2BSettings"
                raise ValueError(msg)
            service = cls._create_e2b_impl(
                e2b=e2b, client=e2b_client, config=config, environment=environment
            )
        else:
            service = cls._create_docker_impl(
                config=config,
                token_service=token_service,
                environment=environment,
                capture_source_instance_id=capture_source_instance_id,
                credential_policy=credential_policy,
            )
        service._platform_tokens = platform_tokens
        service._memory_ledger = memory_ledger
        return service

    @classmethod
    def _create_docker_impl(
        cls,
        config: WorkspaceServiceConfig | None = None,
        token_service: object | None = None,
        environment: dict[str, str] | None = None,
        capture_source_instance_id: str | None = None,
        credential_policy: WorkspaceCredentialPolicy = HOST_CREDENTIALS,
    ) -> WorkspaceService:
        """Internal: Create WorkspaceService with Docker backend."""
        from agentic_isolation import SecurityConfig

        from syn_adapters.workspace_backends.agentic import (
            AgenticEventStreamAdapter,
            AgenticIsolationAdapter,
        )
        from syn_adapters.workspace_backends.agentic.runtime_mapping import to_aw_runtime
        from syn_adapters.workspace_backends.backend_kit import BackendKit
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
                # replace(), not a field-by-field copy: a copy silently drops
                # any field added later.
                cfg = dataclasses.replace(cfg, environment=merged_env)
        else:
            cfg = WorkspaceServiceConfig(environment=environment or {})

        # Choose security profile based on backend type
        # LOCAL is test-only → development(); everything else (DOCKER_HARDENED, GVISOR) → production()
        # with the operator's runtime. Whether that runtime exists on the host,
        # and what auto picks, is agentic-workspace's resolver's to decide.
        security = (
            SecurityConfig.development()
            if cfg.backend == IsolationBackendType.LOCAL
            else dataclasses.replace(
                SecurityConfig.production(), runtime=to_aw_runtime(cfg.runtime)
            )
        )

        # Create adapters using agentic_isolation
        # The Docker BackendKit (#1914): image verification, capture and the
        # credential policy are decided here, once, for every workspace.
        kit = BackendKit(
            default_image=cfg.image,
            credential_policy=credential_policy,
            capture_source_instance_id=capture_source_instance_id,
        )
        isolation = AgenticIsolationAdapter(security=security, kit=kit)
        event_stream = AgenticEventStreamAdapter(isolation)

        # Shared Envoy proxy for credential injection (ISS-43).
        # Agents never see API keys — the proxy injects them via ext_authz.
        proxy_url = os.environ.get("SYN_PROXY_URL", "http://envoy-proxy:8081")
        sidecar = SharedEnvoyAdapter(proxy_url=proxy_url)

        # Token vending
        tvs = token_service or get_token_vending_service()
        vending = TokenVendingServiceAdapter(tvs)  # type: ignore[arg-type]
        token_injection = SidecarTokenInjectionAdapter(vending, sidecar)

        return cls(
            isolation=isolation,  # type: ignore[arg-type]
            sidecar=sidecar,
            token_injection=token_injection,
            event_stream=event_stream,
            config=cfg,
            credential_policy=kit.credential_policy,
        )

    @classmethod
    def _create_e2b_impl(
        cls,
        *,
        e2b: E2BSettings,
        client: E2BSandboxClient | None,
        config: WorkspaceServiceConfig | None,
        environment: dict[str, str] | None,
    ) -> WorkspaceService:
        """Internal: the E2B backend (#1915), through the same adapters as Docker.

        Only the kit and the provider differ. The kit is NoCredentials, so
        ``create_workspace`` refuses the sidecar and token injection for every
        E2B workspace; they are wired as for Docker only to fill the facade.
        """
        from agentic_isolation import E2BWorkspaceProvider
        from agentic_isolation.providers.e2b_client import SdkE2BClient

        from syn_adapters.workspace_backends.agentic import (
            AgenticEventStreamAdapter,
            AgenticIsolationAdapter,
        )
        from syn_adapters.workspace_backends.backend_kit import BackendKit
        from syn_adapters.workspace_backends.docker import SharedEnvoyAdapter
        from syn_adapters.workspace_backends.tokens import (
            SidecarTokenInjectionAdapter,
            TokenVendingServiceAdapter,
        )
        from syn_tokens.vending import get_token_vending_service

        if not e2b.enabled or e2b.api_key is None:
            msg = "The E2B backend was selected but SYN_E2B_ENABLED/SYN_E2B_API_KEY are unset"
            raise ValueError(msg)
        kit = BackendKit.e2b(e2b.template, cpu_count=e2b.cpu_count, memory_mb=e2b.memory_mb)
        sandboxes = client or SdkE2BClient(api_key=e2b.api_key.get_secret_value())
        base = config or WorkspaceServiceConfig()
        cfg = dataclasses.replace(
            base,
            image=kit.default_image,
            environment={**base.environment, **(environment or {})},
        )
        # The provider resolves launch credentials through the adapter's
        # resolver, as Docker's does; without one it refuses them all (#1912).
        isolation = AgenticIsolationAdapter(
            kit=kit,
            provider=lambda credentials: E2BWorkspaceProvider(
                e2b.template,
                client=sandboxes,
                lifetime_seconds=e2b.timeout_seconds,
                credentials=credentials,
            ),
        )
        sidecar = SharedEnvoyAdapter(proxy_url=os.environ.get("SYN_PROXY_URL", ""))
        vending = TokenVendingServiceAdapter(get_token_vending_service())  # type: ignore[arg-type]
        return cls(
            isolation=isolation,  # type: ignore[arg-type]
            sidecar=sidecar,
            token_injection=SidecarTokenInjectionAdapter(vending, sidecar),
            event_stream=AgenticEventStreamAdapter(isolation),
            config=cfg,
            credential_policy=kit.credential_policy,
        )

    @classmethod
    def _create_memory_impl(
        cls,
        config: WorkspaceServiceConfig | None = None,
        credential_policy: WorkspaceCredentialPolicy = HOST_CREDENTIALS,
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
            event_stream=event_stream,
            config=cfg,
            credential_policy=credential_policy,
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
        token_injection = SidecarTokenInjectionAdapter(vending, sidecar)

        return cls(
            isolation=isolation,
            sidecar=sidecar,
            token_injection=token_injection,
            event_stream=event_stream,
            config=cfg,
        )

    def _build_workspace_aggregate_and_config(
        self,
        workspace_id: str,
        execution_id: str,
        workflow_id: str | None,
        phase_id: str | None,
        extra_environment: dict[str, str] | None,
        capture_session_id: str | None = None,
        memory_mb: int | None = None,
        pids_limit: int | None = None,
    ) -> tuple[WorkspaceAggregate, IsolationConfig]:
        """Create aggregate and isolation config for a new workspace.

        Args:
            workspace_id: Unique workspace ID
            execution_id: Execution ID for audit trail
            workflow_id: Optional workflow ID
            phase_id: Optional phase ID
            extra_environment: Additional environment variables
            memory_mb: This workspace's memory; None is the configured default.
            pids_limit: This workspace's pids limit; None is the configured default.

        Returns:
            Tuple of (WorkspaceAggregate, IsolationConfig).
        """
        isolation_config = build_isolation_config(
            config=self._config,
            workspace_id=workspace_id,
            execution_id=execution_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            extra_environment=extra_environment,
            capture_session_id=capture_session_id,
            memory_limit_mb=memory_mb,
            pids_limit=pids_limit,
        )
        aggregate = create_workspace_aggregate(
            workspace_id=workspace_id,
            execution_id=execution_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            backend=self._config.backend,
            capabilities=self._config.capabilities,
            image=self._config.image,
            # The limits the container is actually given, recorded on
            # WorkspaceCreated rather than the SecurityPolicy defaults.
            security_policy=isolation_config.security_policy,
        )

        return aggregate, isolation_config

    @staticmethod
    def _settle_reservation(
        reservation: LedgerReservation,
        execution_id: str,
        track: ProvisionTrack,
        isolation_handle: IsolationHandle | None,
        teardown: IsolationTeardown | None,
    ) -> None:
        """Release only when the container is shown gone; otherwise leave it charged."""
        reason = _not_shown_gone(track, isolation_handle, teardown)
        if reason is None:
            reservation.release()
        else:
            reservation.leak(execution_id, reason=reason)

    async def _reserve_memory(self, memory_mb: int, workspace_id: str) -> LedgerReservation | None:
        """Hold ``memory_mb`` of this process's workspace memory, waiting if it is taken."""
        if self._memory_ledger is None:
            return None
        return await self._memory_ledger.reserve(memory_mb, workspace_id=workspace_id)

    async def _revoke_platform_grant(self, workspace: ManagedWorkspace) -> None:
        """The phase is over, so its API token is too (ADR-072). Never raises."""
        grant = workspace.platform_grant
        if grant is None or self._platform_tokens is None:
            return
        try:
            await self._platform_tokens.revoke(grant.token)
        except Exception:
            logger.exception(
                "Could not revoke the platform token of workspace %s; it stays usable "
                "until it expires (SYN_PLATFORM_ACCESS_TOKEN_TTL_SECONDS).",
                workspace.workspace_id,
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
        extra_environment: dict[str, str] | None = None,
        capture_session_id: str | None = None,
        platform_access: PlatformScope = PlatformScope.READ,
        eval_id: str | None = None,
        resources: WorkspaceResourceRequest | None = None,
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
            platform_access: Scope of the workspace's platform token, as the
                phase declared it (ADR-072, #1744). READ unless declared.
            eval_id: The eval the execution belongs to; the only eval an EVAL
                token can launch into or score (#1744).
            resources: What the phase asked its workspace to be (okrs-51p.30).
                None or empty: the configured default. A request above
                ``memory_max_mb`` raises ``WorkspaceMemoryOverCapError``, and
                one above ``pids_max`` raises ``WorkspacePidsOverCapError``,
                before any container or token exists.

        Yields:
            ManagedWorkspace for command execution
        """
        import uuid

        _refuse_credentials_under(self._credential_policy, with_sidecar, inject_tokens)
        wanted = resources or WorkspaceResourceRequest()
        # The last of three places this is checked (install, start, here), and
        # the one that holds whatever the other two missed: never clamp.
        require_memory_within_cap(wanted, self._config.memory_max_mb, phase_id=phase_id)
        require_pids_within_cap(wanted, self._config.pids_max, phase_id=phase_id)
        memory_mb = wanted.memory_mb_or(self._config.memory_limit_mb)

        workspace_id = str(uuid.uuid4())

        aggregate, isolation_config = self._build_workspace_aggregate_and_config(
            workspace_id,
            execution_id,
            workflow_id,
            phase_id,
            extra_environment,
            capture_session_id,
            memory_mb=memory_mb,
            pids_limit=wanted.pids_limit_or(self._config.pids_limit),
        )
        reservation = await self._reserve_memory(memory_mb, workspace_id)

        isolation_handle: IsolationHandle | None = None
        sidecar_handle: SidecarHandle | None = None
        workspace: ManagedWorkspace | None = None
        track = ProvisionTrack()
        if reservation is not None:
            # Until the create and whatever removes its container are over,
            # no listing can show this workspace gone.
            reservation.create_started()

        try:
            isolation_handle, sidecar_handle, image_manifest = await provision_workspace(
                self,
                isolation_config,
                aggregate,
                workspace_id,
                with_sidecar=with_sidecar,
                track=track,
            )

            workspace = ManagedWorkspace(
                workspace_id=workspace_id,
                execution_id=execution_id,
                aggregate=aggregate,
                isolation_handle=isolation_handle,
                sidecar_handle=sidecar_handle,
                image_manifest=image_manifest,
                _service=self,
            )

            if inject_tokens and sidecar_handle:
                types = token_types or [TokenType.ANTHROPIC]
                await workspace.inject_tokens(types)

            if self._platform_tokens is not None and self._credential_policy.supplies_credentials:
                workspace.platform_grant = await self._platform_tokens.grant_workspace(
                    execution_id, platform_access, eval_id
                )

            yield workspace

        except Exception as e:
            if aggregate:
                aggregate.record_error(str(e), str(type(e).__name__))
            logger.exception("Workspace error (id=%s): %s", workspace_id, e)
            raise

        finally:
            # After the caller's block, and so after the unpushed-work guard's
            # quarantine push: nothing left in the container needs a token (#725).
            # The handle as soon as the container existed, not only once
            # provisioning returned: a sidecar that failed to start used to
            # leave the container undestroyed (okrs-51p.30, Codex on #2148).
            isolation_handle = isolation_handle or track.created()
            if track.create_task is not None and track.still_creating():
                # Cancelled mid-create: the `docker run` carries on. See it
                # through and destroy what it makes, off this frame.
                finish_abandoned_create(
                    self,
                    track.create_task,
                    execution_id=execution_id,
                    on_end=reservation.create_ended if reservation is not None else _nothing,
                )
            elif reservation is not None:
                reservation.create_ended()
            teardown: IsolationTeardown | None = None
            try:
                if workspace is not None:
                    await workspace.revoke_issued_credentials()
                    await self._revoke_platform_grant(workspace)
                teardown = await cleanup_workspace(
                    self,
                    aggregate,
                    workspace_id,
                    execution_id,
                    isolation_handle=isolation_handle,
                    sidecar_handle=sidecar_handle,
                    inject_tokens=inject_tokens,
                    phase_id=phase_id,
                )
            finally:
                # The memory is the container's until it is SHOWN gone.
                if reservation is not None:
                    self._settle_reservation(
                        reservation, execution_id, track, isolation_handle, teardown
                    )
            # Handed back on the object every caller still holds after
            # `__aexit__`, so the frame that knows the session can record it.
            # (teardown is None only when cleanup raised, which never gets here.)
            if workspace is not None and teardown is not None:
                workspace.teardown_usage = teardown.usage
                workspace.teardown_failure = teardown.failure
