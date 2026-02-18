"""WorkspaceAggregate - Event-sourced aggregate root for isolated workspaces.

This aggregate manages the lifecycle of an isolated workspace:
1. Creation: Provision isolation environment + optional sidecar
2. Token Injection: Inject API tokens via sidecar (ADR-022)
3. Git Configuration: Set up git credentials and clone repo
4. Command Execution: Execute commands and stream events
5. Artifact Collection: Collect outputs for persistence
6. Termination: Clean up resources, revoke tokens

All operations are event-sourced for audit trail and state reconstruction.

Location: orchestration/domain/aggregate_workspace/ (per ADR-020)

Usage:
    # Create aggregate (domain layer - no ports yet)
    aggregate = WorkspaceAggregate()

    # Handle command (raises events)
    aggregate.create_workspace(CreateWorkspaceCommand(...))

    # Events are persisted to event store
    for event in aggregate.uncommitted_events:
        event_store.append(event)

    # State is reconstructed from events
    aggregate = WorkspaceAggregate.load(events)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    CapabilityType,
    ExecutionResult,
    InjectionMethod,
    IsolationBackendType,
    IsolationHandle,
    SecurityPolicy,
    SidecarHandle,
    TokenType,
    WorkspaceStatus,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.commands.CreateWorkspaceCommand import (
        CreateWorkspaceCommand,
    )
    from syn_domain.contexts.orchestration.domain.commands.ExecuteCommandCommand import (
        ExecuteCommandCommand,
    )
    from syn_domain.contexts.orchestration.domain.commands.InjectTokensCommand import (
        InjectTokensCommand,
    )
    from syn_domain.contexts.orchestration.domain.commands.TerminateWorkspaceCommand import (
        TerminateWorkspaceCommand,
    )
    from syn_domain.contexts.orchestration.domain.events.CommandExecutedEvent import (
        CommandExecutedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.CommandFailedEvent import (
        CommandFailedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.IsolationStartedEvent import (
        IsolationStartedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.TokensInjectedEvent import (
        TokensInjectedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkspaceCreatedEvent import (
        WorkspaceCreatedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkspaceErrorEvent import (
        WorkspaceErrorEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkspaceTerminatedEvent import (
        WorkspaceTerminatedEvent,
    )


@aggregate("Workspace")
class WorkspaceAggregate(AggregateRoot["WorkspaceCreatedEvent"]):
    """Workspace aggregate root.

    Manages an isolated workspace lifecycle with event sourcing.

    Invariants:
    - Workspace must be READY before executing commands
    - Workspace must be READY or RUNNING before token injection
    - Terminated workspace cannot accept any operations
    - Commands can only be executed after isolation is started
    """

    # Type hint for decorator-set attribute
    _aggregate_type: str

    def __init__(self) -> None:
        """Initialize aggregate with default state."""
        super().__init__()

        # Identity
        self._workspace_id: str | None = None
        self._execution_id: str | None = None
        self._workflow_id: str | None = None
        self._phase_id: str | None = None

        # Status
        self._status: WorkspaceStatus = WorkspaceStatus.PENDING

        # Isolation
        self._isolation_backend: IsolationBackendType | None = None
        self._isolation_handle: IsolationHandle | None = None
        self._security_policy: SecurityPolicy | None = None
        self._capabilities: tuple[CapabilityType, ...] = ()

        # Sidecar
        self._sidecar_handle: SidecarHandle | None = None
        self._sidecar_enabled: bool = False

        # Tokens
        self._injected_tokens: tuple[TokenType, ...] = ()
        self._injection_method: InjectionMethod | None = None
        self._tokens_ttl_seconds: int | None = None

        # Execution stats
        self._commands_executed: int = 0
        self._commands_succeeded: int = 0
        self._commands_failed: int = 0
        self._total_execution_time_ms: float = 0.0

        # Lifecycle
        self._created_at: datetime | None = None
        self._terminated_at: datetime | None = None
        self._termination_reason: str | None = None

        # Metadata
        self._metadata: dict[str, str | int | float | bool | None] = {}

    def get_aggregate_type(self) -> str:
        """Return aggregate type name."""
        return self._aggregate_type

    # =========================================================================
    # PROPERTIES (Read-only state)
    # =========================================================================

    @property
    def workspace_id(self) -> str | None:
        """Get workspace ID."""
        return self._workspace_id

    @property
    def execution_id(self) -> str | None:
        """Get associated execution ID."""
        return self._execution_id

    @property
    def workflow_id(self) -> str | None:
        """Get associated workflow ID."""
        return self._workflow_id

    @property
    def phase_id(self) -> str | None:
        """Get associated phase ID."""
        return self._phase_id

    @property
    def status(self) -> WorkspaceStatus:
        """Get current workspace status."""
        return self._status

    @property
    def isolation_backend(self) -> IsolationBackendType | None:
        """Get isolation backend type."""
        return self._isolation_backend

    @property
    def isolation_handle(self) -> IsolationHandle | None:
        """Get isolation handle (container/VM reference)."""
        return self._isolation_handle

    @property
    def sidecar_handle(self) -> SidecarHandle | None:
        """Get sidecar handle."""
        return self._sidecar_handle

    @property
    def sidecar_enabled(self) -> bool:
        """Check if sidecar is enabled."""
        return self._sidecar_enabled

    @property
    def capabilities(self) -> tuple[CapabilityType, ...]:
        """Get enabled capabilities."""
        return self._capabilities

    @property
    def injected_tokens(self) -> tuple[TokenType, ...]:
        """Get injected token types."""
        return self._injected_tokens

    @property
    def commands_executed(self) -> int:
        """Get total commands executed."""
        return self._commands_executed

    @property
    def commands_succeeded(self) -> int:
        """Get successful commands count."""
        return self._commands_succeeded

    @property
    def commands_failed(self) -> int:
        """Get failed commands count."""
        return self._commands_failed

    @property
    def total_execution_time_ms(self) -> float:
        """Get total command execution time."""
        return self._total_execution_time_ms

    @property
    def created_at(self) -> datetime | None:
        """Get workspace creation timestamp."""
        return self._created_at

    @property
    def terminated_at(self) -> datetime | None:
        """Get workspace termination timestamp."""
        return self._terminated_at

    @property
    def lifetime_seconds(self) -> float | None:
        """Get workspace lifetime in seconds."""
        if self._created_at is None:
            return None
        end = self._terminated_at or datetime.now(UTC)
        return (end - self._created_at).total_seconds()

    @property
    def is_terminated(self) -> bool:
        """Check if workspace is terminated."""
        return self._status in (WorkspaceStatus.DESTROYED, WorkspaceStatus.ERROR)

    @property
    def can_execute_commands(self) -> bool:
        """Check if workspace can execute commands."""
        return self._status in (WorkspaceStatus.READY, WorkspaceStatus.RUNNING)

    # =========================================================================
    # COMMAND HANDLERS
    # =========================================================================

    @command_handler("CreateWorkspaceCommand")
    def create_workspace(self, command: CreateWorkspaceCommand) -> None:
        """Handle CreateWorkspaceCommand.

        Creates a new workspace with isolation and optional sidecar.
        """
        from syn_domain.contexts.orchestration.domain.events.WorkspaceCreatedEvent import (
            WorkspaceCreatedEvent,
        )

        # Validate: workspace must not already exist
        if self.id is not None:
            msg = "Workspace already exists"
            raise ValueError(msg)

        # Validate required fields
        if not command.execution_id:
            msg = "execution_id is required"
            raise ValueError(msg)

        # Generate workspace ID
        workspace_id = command.aggregate_id or str(uuid4())

        # Initialize aggregate
        self._initialize(workspace_id)

        # Create event
        event = WorkspaceCreatedEvent(
            workspace_id=workspace_id,
            session_id=command.execution_id,  # For backward compat with existing event schema
            workflow_id=command.workflow_id,
            execution_id=command.execution_id,
            phase_id=command.phase_id,
            isolation_backend=command.isolation_backend.value,
            container_id=None,  # Set by IsolationStartedEvent
            created_at=datetime.now(UTC),
            create_duration_ms=0.0,  # Updated by IsolationStartedEvent
            workspace_path=command.working_directory,
            security_settings=command.security_policy.model_dump()
            if hasattr(command.security_policy, "model_dump")
            else {},
        )

        self._apply(event)

    @command_handler("InjectTokensCommand")
    def inject_tokens(self, command: InjectTokensCommand) -> None:
        """Handle InjectTokensCommand.

        Injects API tokens via sidecar or direct injection.
        """
        from syn_domain.contexts.orchestration.domain.events.TokensInjectedEvent import (
            TokensInjectedEvent,
        )

        # Validate: workspace must exist and be ready
        if self._workspace_id is None:
            msg = "Workspace does not exist"
            raise ValueError(msg)

        if not self.can_execute_commands:
            msg = f"Cannot inject tokens: workspace is {self._status.value}"
            raise ValueError(msg)

        # Validate: must have token types
        if not command.token_types:
            msg = "At least one token type is required"
            raise ValueError(msg)

        # Determine injection method
        injection_method = (
            InjectionMethod.SIDECAR if self._sidecar_enabled else InjectionMethod.ENV_VAR
        )

        # Create event
        event = TokensInjectedEvent(
            workspace_id=str(self._workspace_id),
            token_types=[t.value for t in command.token_types],
            ttl_seconds=command.ttl_seconds,
            injected_via=injection_method.value,
            injected_at=datetime.now(UTC),
        )

        self._apply(event)  # type: ignore[arg-type]

    @command_handler("ExecuteCommandCommand")
    def execute_command(self, command: ExecuteCommandCommand) -> None:
        """Handle ExecuteCommandCommand.

        Records a command execution result.
        Note: Actual execution is done by the application layer via ports.
        """
        from syn_domain.contexts.orchestration.domain.events.CommandExecutedEvent import (
            CommandExecutedEvent,
        )
        from syn_domain.contexts.orchestration.domain.events.CommandFailedEvent import (
            CommandFailedEvent,
        )

        # Validate: workspace must be ready
        if not self.can_execute_commands:
            msg = f"Cannot execute command: workspace is {self._status.value}"
            raise ValueError(msg)

        # Validate: must have command
        if not command.command:
            msg = "Command is required"
            raise ValueError(msg)

        # Result should be provided by application layer
        if command.result is None:
            msg = "Execution result is required (provided by application layer)"
            raise ValueError(msg)

        result: ExecutionResult = command.result

        # Create appropriate event based on success
        event: CommandExecutedEvent | CommandFailedEvent
        if result.success:
            event = CommandExecutedEvent(
                workspace_id=str(self._workspace_id),
                command=command.command,
                exit_code=result.exit_code,
                success=True,
                duration_ms=result.duration_ms,
                stdout_lines=result.stdout_lines,
                stderr_lines=result.stderr_lines,
                executed_at=datetime.now(UTC),
            )
        else:
            event = CommandFailedEvent(
                workspace_id=str(self._workspace_id),
                command=command.command,
                exit_code=result.exit_code,
                error_message=result.stderr[:500] if result.stderr else "Unknown error",
                duration_ms=result.duration_ms,
                timed_out=result.timed_out,
                failed_at=datetime.now(UTC),
            )

        self._apply(event)  # type: ignore[arg-type]

    @command_handler("TerminateWorkspaceCommand")
    def terminate_workspace(self, command: TerminateWorkspaceCommand) -> None:
        """Handle TerminateWorkspaceCommand.

        Marks workspace as terminated and records cleanup.
        """
        from syn_domain.contexts.orchestration.domain.events.WorkspaceTerminatedEvent import (
            WorkspaceTerminatedEvent,
        )

        # Validate: workspace must exist
        if self._workspace_id is None:
            msg = "Workspace does not exist"
            raise ValueError(msg)

        # Idempotent: allow terminating already terminated workspace
        if self.is_terminated:
            return

        # Create event
        event = WorkspaceTerminatedEvent(
            workspace_id=str(self._workspace_id),
            reason=command.reason,
            total_commands=self._commands_executed,
            total_duration_seconds=self.lifetime_seconds or 0.0,
            terminated_at=datetime.now(UTC),
        )

        self._apply(event)  # type: ignore[arg-type]

    # =========================================================================
    # NON-COMMAND METHODS (for recording events without commands)
    # =========================================================================

    def record_isolation_started(
        self,
        isolation_id: str,
        isolation_type: str,
        proxy_url: str | None = None,
        started_at: datetime | None = None,
    ) -> None:
        """Record that isolation has started.

        Called by application layer after IsolationBackendPort.create() succeeds.
        """
        from syn_domain.contexts.orchestration.domain.events.IsolationStartedEvent import (
            IsolationStartedEvent,
        )

        if self._workspace_id is None:
            msg = "Workspace must be created first"
            raise ValueError(msg)

        event = IsolationStartedEvent(
            workspace_id=str(self._workspace_id),
            isolation_id=isolation_id,
            isolation_type=isolation_type,
            proxy_url=proxy_url,
            started_at=started_at or datetime.now(UTC),
        )

        self._apply(event)  # type: ignore[arg-type]

    def record_error(
        self,
        error_type: str,
        error_message: str,
        operation: str = "unknown",
    ) -> None:
        """Record an error that occurred during workspace operations.

        Transitions workspace to ERROR state.

        Args:
            error_type: Type of error (e.g., "isolation_failure", "timeout")
            error_message: Human-readable error message
            operation: Operation that failed (e.g., "create", "execute", "destroy")
        """
        from syn_domain.contexts.orchestration.domain.events.WorkspaceErrorEvent import (
            WorkspaceErrorEvent,
        )

        if self._workspace_id is None:
            msg = "Workspace must be created first"
            raise ValueError(msg)

        event = WorkspaceErrorEvent(
            workspace_id=str(self._workspace_id),
            session_id=str(self._execution_id or ""),
            operation=operation,
            error_type=error_type,
            error_message=error_message,
            occurred_at=datetime.now(UTC),
        )

        self._apply(event)  # type: ignore[arg-type]

    # =========================================================================
    # EVENT SOURCING HANDLERS
    # =========================================================================

    @event_sourcing_handler("WorkspaceCreated")
    def on_workspace_created(self, event: WorkspaceCreatedEvent) -> None:
        """Apply WorkspaceCreatedEvent."""
        self._workspace_id = event.workspace_id
        self._execution_id = event.execution_id or event.session_id
        self._workflow_id = event.workflow_id
        self._phase_id = event.phase_id
        self._isolation_backend = IsolationBackendType(event.isolation_backend)
        self._created_at = event.created_at
        self._status = WorkspaceStatus.CREATING

        # Parse security settings if provided
        if event.security_settings:
            # Could reconstruct SecurityPolicy here if needed
            pass

    @event_sourcing_handler("IsolationStarted")
    def on_isolation_started(self, event: IsolationStartedEvent) -> None:
        """Apply IsolationStartedEvent."""
        self._isolation_handle = IsolationHandle(
            isolation_id=event.isolation_id,
            isolation_type=event.isolation_type,
            proxy_url=event.proxy_url,
        )
        self._sidecar_enabled = event.proxy_url is not None
        self._status = WorkspaceStatus.READY

    @event_sourcing_handler("TokensInjected")
    def on_tokens_injected(self, event: TokensInjectedEvent) -> None:
        """Apply TokensInjectedEvent."""
        self._injected_tokens = tuple(TokenType(t) for t in event.token_types)
        self._injection_method = InjectionMethod(event.injected_via)
        self._tokens_ttl_seconds = event.ttl_seconds

    @event_sourcing_handler("WorkspaceCommandExecuted")
    def on_command_executed(self, event: CommandExecutedEvent) -> None:
        """Apply CommandExecutedEvent (legacy name for backward compat)."""
        self._commands_executed += 1
        self._commands_succeeded += 1
        self._total_execution_time_ms += event.duration_ms
        self._status = WorkspaceStatus.RUNNING

    @event_sourcing_handler("CommandExecuted")
    def on_command_executed_v2(self, event: CommandExecutedEvent) -> None:
        """Apply CommandExecutedEvent (new name)."""
        self.on_command_executed(event)

    @event_sourcing_handler("CommandFailed")
    def on_command_failed(self, event: CommandFailedEvent) -> None:
        """Apply CommandFailedEvent."""
        self._commands_executed += 1
        self._commands_failed += 1
        self._total_execution_time_ms += event.duration_ms
        self._status = WorkspaceStatus.RUNNING

    @event_sourcing_handler("WorkspaceTerminated")
    def on_workspace_terminated(self, event: WorkspaceTerminatedEvent) -> None:
        """Apply WorkspaceTerminatedEvent."""
        self._terminated_at = event.terminated_at
        self._termination_reason = event.reason
        self._status = WorkspaceStatus.DESTROYED

    @event_sourcing_handler("WorkspaceDestroyed")
    def on_workspace_destroyed(self, event: WorkspaceTerminatedEvent) -> None:
        """Apply WorkspaceDestroyedEvent (legacy, same as terminated)."""
        self.on_workspace_terminated(event)

    @event_sourcing_handler("WorkspaceError")
    def on_workspace_error(self, event: WorkspaceErrorEvent) -> None:
        """Apply WorkspaceErrorEvent."""
        self._status = WorkspaceStatus.ERROR
        self._metadata["last_error_type"] = event.error_type
        self._metadata["last_error_message"] = event.error_message
