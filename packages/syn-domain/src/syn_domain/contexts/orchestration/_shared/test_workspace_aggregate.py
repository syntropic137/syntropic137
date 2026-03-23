"""Unit tests for WorkspaceAggregate.

Tests the event-sourced aggregate with mocks (no Docker, no network).
Follows DI principles - aggregate is tested in isolation.

Run: pytest packages/syn-domain/src/syn_domain/contexts/workspaces/_shared/test_workspace_aggregate.py -v
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    CapabilityType,
    ExecutionResult,
    InjectionMethod,
    IsolationBackendType,
    SecurityPolicy,
    TokenType,
    WorkspaceStatus,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.WorkspaceAggregate import (
    WorkspaceAggregate,
    _build_command_event,
)
from syn_domain.contexts.orchestration.domain.events.CommandExecutedEvent import (
    CommandExecutedEvent,
)
from syn_domain.contexts.orchestration.domain.events.CommandFailedEvent import CommandFailedEvent
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

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def aggregate() -> WorkspaceAggregate:
    """Create a fresh WorkspaceAggregate."""
    return WorkspaceAggregate()


@pytest.fixture
def created_aggregate() -> WorkspaceAggregate:
    """Create an aggregate with workspace already created."""
    agg = WorkspaceAggregate()
    cmd = CreateWorkspaceCommand(
        execution_id="exec-123",
        workflow_id="wf-456",
        phase_id="phase-1",
        isolation_backend=IsolationBackendType.DOCKER_HARDENED,
        capabilities=(CapabilityType.NETWORK, CapabilityType.GIT),
    )
    agg.create_workspace(cmd)
    return agg


@pytest.fixture
def ready_aggregate() -> WorkspaceAggregate:
    """Create an aggregate with workspace ready (isolation started)."""
    agg = WorkspaceAggregate()
    cmd = CreateWorkspaceCommand(
        execution_id="exec-123",
        workflow_id="wf-456",
        isolation_backend=IsolationBackendType.DOCKER_HARDENED,
    )
    agg.create_workspace(cmd)
    agg.record_isolation_started(
        isolation_id="container-abc123",
        isolation_type="docker",
        proxy_url="http://localhost:8080",
    )
    return agg


# =============================================================================
# CREATE WORKSPACE TESTS
# =============================================================================


@pytest.mark.integration
class TestCreateWorkspace:
    """Tests for CreateWorkspaceCommand handling."""

    def test_create_workspace_success(self, aggregate: WorkspaceAggregate) -> None:
        """Test successful workspace creation."""
        cmd = CreateWorkspaceCommand(
            execution_id="exec-123",
            workflow_id="wf-456",
            phase_id="phase-1",
            isolation_backend=IsolationBackendType.DOCKER_HARDENED,
            capabilities=(CapabilityType.NETWORK, CapabilityType.GIT),
            security_policy=SecurityPolicy(memory_limit_mb=2048),
        )

        aggregate.create_workspace(cmd)

        # Verify state
        assert aggregate.workspace_id is not None
        assert aggregate.execution_id == "exec-123"
        assert aggregate.workflow_id == "wf-456"
        assert aggregate.phase_id == "phase-1"
        assert aggregate.isolation_backend == IsolationBackendType.DOCKER_HARDENED
        assert aggregate.status == WorkspaceStatus.CREATING
        assert aggregate.created_at is not None

    def test_create_workspace_generates_id(self, aggregate: WorkspaceAggregate) -> None:
        """Test that workspace ID is auto-generated if not provided."""
        cmd = CreateWorkspaceCommand(execution_id="exec-123")

        aggregate.create_workspace(cmd)

        assert aggregate.workspace_id is not None
        assert len(aggregate.workspace_id) == 36  # UUID length

    def test_create_workspace_uses_provided_id(self, aggregate: WorkspaceAggregate) -> None:
        """Test that provided aggregate_id is used."""
        cmd = CreateWorkspaceCommand(
            execution_id="exec-123",
            aggregate_id="my-workspace-id",
        )

        aggregate.create_workspace(cmd)

        assert aggregate.workspace_id == "my-workspace-id"

    def test_create_workspace_requires_execution_id(self, aggregate: WorkspaceAggregate) -> None:
        """Test that execution_id is required."""
        cmd = CreateWorkspaceCommand(execution_id="")

        with pytest.raises(ValueError, match="execution_id is required"):
            aggregate.create_workspace(cmd)

    def test_create_workspace_fails_if_already_exists(
        self, created_aggregate: WorkspaceAggregate
    ) -> None:
        """Test that creating workspace twice fails."""
        cmd = CreateWorkspaceCommand(execution_id="exec-456")

        with pytest.raises(ValueError, match="Workspace already exists"):
            created_aggregate.create_workspace(cmd)

    def test_create_workspace_emits_event(self, aggregate: WorkspaceAggregate) -> None:
        """Test that WorkspaceCreatedEvent is emitted."""
        cmd = CreateWorkspaceCommand(
            execution_id="exec-123",
            isolation_backend=IsolationBackendType.GVISOR,
        )

        aggregate.create_workspace(cmd)

        # Check uncommitted events (internal attribute - returns EventEnvelope)
        events = list(aggregate._uncommitted_events)
        assert len(events) == 1
        assert events[0].event.event_type == "WorkspaceCreated"


# =============================================================================
# ISOLATION STARTED TESTS
# =============================================================================


class TestIsolationStarted:
    """Tests for recording isolation started."""

    def test_isolation_started_success(self, created_aggregate: WorkspaceAggregate) -> None:
        """Test successful isolation started recording."""
        created_aggregate.record_isolation_started(
            isolation_id="container-abc123",
            isolation_type="docker",
            proxy_url="http://localhost:8080",
        )

        # Verify state
        assert created_aggregate.status == WorkspaceStatus.READY
        assert created_aggregate.isolation_handle is not None
        assert created_aggregate.isolation_handle.isolation_id == "container-abc123"
        assert created_aggregate.isolation_handle.isolation_type == "docker"
        assert created_aggregate.isolation_handle.proxy_url == "http://localhost:8080"
        assert created_aggregate.sidecar_enabled is True

    def test_isolation_started_without_sidecar(self, created_aggregate: WorkspaceAggregate) -> None:
        """Test isolation started without sidecar (no proxy_url)."""
        created_aggregate.record_isolation_started(
            isolation_id="container-abc123",
            isolation_type="docker",
            proxy_url=None,
        )

        assert created_aggregate.sidecar_enabled is False

    def test_isolation_started_requires_workspace(self, aggregate: WorkspaceAggregate) -> None:
        """Test that workspace must exist before recording isolation."""
        with pytest.raises(ValueError, match="Workspace must be created first"):
            aggregate.record_isolation_started(
                isolation_id="container-abc123",
                isolation_type="docker",
            )


# =============================================================================
# INJECT TOKENS TESTS
# =============================================================================


class TestInjectTokens:
    """Tests for InjectTokensCommand handling."""

    def test_inject_tokens_success(self, ready_aggregate: WorkspaceAggregate) -> None:
        """Test successful token injection."""
        cmd = InjectTokensCommand(
            workspace_id=str(ready_aggregate.workspace_id),
            token_types=(TokenType.ANTHROPIC, TokenType.GITHUB),
            ttl_seconds=600,
        )

        ready_aggregate.inject_tokens(cmd)

        # Verify state
        assert TokenType.ANTHROPIC in ready_aggregate.injected_tokens
        assert TokenType.GITHUB in ready_aggregate.injected_tokens
        assert ready_aggregate._tokens_ttl_seconds == 600
        # Since sidecar is enabled, injection method should be SIDECAR
        assert ready_aggregate._injection_method == InjectionMethod.SIDECAR

    def test_inject_tokens_via_env_var_without_sidecar(
        self, created_aggregate: WorkspaceAggregate
    ) -> None:
        """Test token injection falls back to env_var without sidecar."""
        # Start isolation without sidecar
        created_aggregate.record_isolation_started(
            isolation_id="container-abc123",
            isolation_type="docker",
            proxy_url=None,  # No sidecar
        )

        cmd = InjectTokensCommand(
            workspace_id=str(created_aggregate.workspace_id),
            token_types=(TokenType.ANTHROPIC,),
        )

        created_aggregate.inject_tokens(cmd)

        assert created_aggregate._injection_method == InjectionMethod.ENV_VAR

    def test_inject_tokens_requires_ready_workspace(
        self, created_aggregate: WorkspaceAggregate
    ) -> None:
        """Test that workspace must be ready to inject tokens."""
        # Workspace is CREATING, not READY
        cmd = InjectTokensCommand(
            workspace_id=str(created_aggregate.workspace_id),
            token_types=(TokenType.ANTHROPIC,),
        )

        with pytest.raises(ValueError, match="Cannot inject tokens"):
            created_aggregate.inject_tokens(cmd)

    def test_inject_tokens_requires_token_types(self, ready_aggregate: WorkspaceAggregate) -> None:
        """Test that at least one token type is required."""
        cmd = InjectTokensCommand(
            workspace_id=str(ready_aggregate.workspace_id),
            token_types=(),  # Empty
        )

        with pytest.raises(ValueError, match="At least one token type"):
            ready_aggregate.inject_tokens(cmd)


# =============================================================================
# EXECUTE COMMAND TESTS
# =============================================================================


class TestExecuteCommand:
    """Tests for ExecuteCommandCommand handling."""

    def test_execute_command_success(self, ready_aggregate: WorkspaceAggregate) -> None:
        """Test successful command execution recording."""
        result = ExecutionResult(
            exit_code=0,
            success=True,
            duration_ms=1500.0,
            stdout="Hello, World!",
            stderr="",
            stdout_lines=1,
            stderr_lines=0,
        )

        cmd = ExecuteCommandCommand(
            workspace_id=str(ready_aggregate.workspace_id),
            command=["python", "-c", "print('Hello, World!')"],
            result=result,
        )

        ready_aggregate.execute_command(cmd)

        # Verify state
        assert ready_aggregate.status == WorkspaceStatus.RUNNING
        assert ready_aggregate.commands_executed == 1
        assert ready_aggregate.commands_succeeded == 1
        assert ready_aggregate.commands_failed == 0
        assert ready_aggregate.total_execution_time_ms == 1500.0

    def test_execute_command_failure(self, ready_aggregate: WorkspaceAggregate) -> None:
        """Test failed command execution recording."""
        result = ExecutionResult(
            exit_code=1,
            success=False,
            duration_ms=500.0,
            stdout="",
            stderr="Error: file not found",
            stdout_lines=0,
            stderr_lines=1,
        )

        cmd = ExecuteCommandCommand(
            workspace_id=str(ready_aggregate.workspace_id),
            command=["cat", "nonexistent.txt"],
            result=result,
        )

        ready_aggregate.execute_command(cmd)

        # Verify state
        assert ready_aggregate.commands_executed == 1
        assert ready_aggregate.commands_succeeded == 0
        assert ready_aggregate.commands_failed == 1

    def test_execute_command_timeout(self, ready_aggregate: WorkspaceAggregate) -> None:
        """Test timed-out command execution recording."""
        result = ExecutionResult(
            exit_code=-1,
            success=False,
            duration_ms=30000.0,
            stdout="",
            stderr="",
            timed_out=True,
        )

        cmd = ExecuteCommandCommand(
            workspace_id=str(ready_aggregate.workspace_id),
            command=["sleep", "infinity"],
            result=result,
        )

        ready_aggregate.execute_command(cmd)

        assert ready_aggregate.commands_failed == 1

    def test_execute_command_requires_ready_workspace(
        self, created_aggregate: WorkspaceAggregate
    ) -> None:
        """Test that workspace must be ready to execute commands."""
        result = ExecutionResult(exit_code=0, success=True, duration_ms=100.0)

        cmd = ExecuteCommandCommand(
            workspace_id=str(created_aggregate.workspace_id),
            command=["echo", "hello"],
            result=result,
        )

        with pytest.raises(ValueError, match="Cannot execute command"):
            created_aggregate.execute_command(cmd)

    def test_execute_command_requires_result(self, ready_aggregate: WorkspaceAggregate) -> None:
        """Test that execution result is required."""
        cmd = ExecuteCommandCommand(
            workspace_id=str(ready_aggregate.workspace_id),
            command=["echo", "hello"],
            result=None,  # Missing
        )

        with pytest.raises(ValueError, match="Execution result is required"):
            ready_aggregate.execute_command(cmd)

    def test_execute_multiple_commands(self, ready_aggregate: WorkspaceAggregate) -> None:
        """Test executing multiple commands."""
        for i in range(3):
            result = ExecutionResult(
                exit_code=0,
                success=True,
                duration_ms=100.0 * (i + 1),
            )
            cmd = ExecuteCommandCommand(
                workspace_id=str(ready_aggregate.workspace_id),
                command=["echo", str(i)],
                result=result,
            )
            ready_aggregate.execute_command(cmd)

        assert ready_aggregate.commands_executed == 3
        assert ready_aggregate.commands_succeeded == 3
        assert ready_aggregate.total_execution_time_ms == 600.0  # 100 + 200 + 300


# =============================================================================
# TERMINATE WORKSPACE TESTS
# =============================================================================


class TestTerminateWorkspace:
    """Tests for TerminateWorkspaceCommand handling."""

    def test_terminate_workspace_success(self, ready_aggregate: WorkspaceAggregate) -> None:
        """Test successful workspace termination."""
        cmd = TerminateWorkspaceCommand(
            workspace_id=str(ready_aggregate.workspace_id),
            reason="completed",
        )

        ready_aggregate.terminate_workspace(cmd)

        # Verify state
        assert ready_aggregate.status == WorkspaceStatus.DESTROYED
        assert ready_aggregate.is_terminated is True
        assert ready_aggregate.terminated_at is not None
        assert ready_aggregate._termination_reason == "completed"

    def test_terminate_workspace_with_stats(self, ready_aggregate: WorkspaceAggregate) -> None:
        """Test termination preserves execution stats."""
        # Execute some commands first
        for _ in range(5):
            result = ExecutionResult(exit_code=0, success=True, duration_ms=100.0)
            cmd = ExecuteCommandCommand(
                workspace_id=str(ready_aggregate.workspace_id),
                command=["echo", "test"],
                result=result,
            )
            ready_aggregate.execute_command(cmd)

        # Terminate
        terminate_cmd = TerminateWorkspaceCommand(
            workspace_id=str(ready_aggregate.workspace_id),
            reason="completed",
        )
        ready_aggregate.terminate_workspace(terminate_cmd)

        # Stats should be preserved
        assert ready_aggregate.commands_executed == 5
        assert ready_aggregate.is_terminated is True

    def test_terminate_workspace_idempotent(self, ready_aggregate: WorkspaceAggregate) -> None:
        """Test that terminating twice is idempotent."""
        cmd = TerminateWorkspaceCommand(
            workspace_id=str(ready_aggregate.workspace_id),
            reason="completed",
        )

        ready_aggregate.terminate_workspace(cmd)
        # Should not raise
        ready_aggregate.terminate_workspace(cmd)

        assert ready_aggregate.is_terminated is True

    def test_cannot_execute_after_termination(self, ready_aggregate: WorkspaceAggregate) -> None:
        """Test that commands cannot be executed after termination."""
        terminate_cmd = TerminateWorkspaceCommand(
            workspace_id=str(ready_aggregate.workspace_id),
            reason="completed",
        )
        ready_aggregate.terminate_workspace(terminate_cmd)

        result = ExecutionResult(exit_code=0, success=True, duration_ms=100.0)
        exec_cmd = ExecuteCommandCommand(
            workspace_id=str(ready_aggregate.workspace_id),
            command=["echo", "hello"],
            result=result,
        )

        with pytest.raises(ValueError, match="Cannot execute command"):
            ready_aggregate.execute_command(exec_cmd)


# =============================================================================
# ERROR RECORDING TESTS
# =============================================================================


class TestRecordError:
    """Tests for error recording."""

    def test_record_error_transitions_to_error_state(
        self, created_aggregate: WorkspaceAggregate
    ) -> None:
        """Test that recording error transitions to ERROR state."""
        created_aggregate.record_error(
            error_type="isolation_failure",
            error_message="Failed to start container",
            operation="create",
        )

        assert created_aggregate.status == WorkspaceStatus.ERROR
        assert created_aggregate._metadata["last_error_type"] == "isolation_failure"
        assert created_aggregate._metadata["last_error_message"] == "Failed to start container"

    def test_record_error_requires_workspace(self, aggregate: WorkspaceAggregate) -> None:
        """Test that workspace must exist to record error."""
        with pytest.raises(ValueError, match="Workspace must be created first"):
            aggregate.record_error(
                error_type="test_error",
                error_message="Test message",
            )


# =============================================================================
# PROPERTY TESTS
# =============================================================================


class TestAggregateProperties:
    """Tests for aggregate properties and computed values."""

    def test_lifetime_seconds_during_execution(self, ready_aggregate: WorkspaceAggregate) -> None:
        """Test lifetime_seconds is calculated correctly."""
        # Should return non-None value for created workspace
        lifetime = ready_aggregate.lifetime_seconds
        assert lifetime is not None
        assert lifetime >= 0

    def test_lifetime_seconds_after_termination(self, ready_aggregate: WorkspaceAggregate) -> None:
        """Test lifetime_seconds is frozen after termination."""
        cmd = TerminateWorkspaceCommand(
            workspace_id=str(ready_aggregate.workspace_id),
            reason="completed",
        )
        ready_aggregate.terminate_workspace(cmd)

        lifetime1 = ready_aggregate.lifetime_seconds
        # Even with time passing, lifetime should be based on terminated_at
        lifetime2 = ready_aggregate.lifetime_seconds

        assert lifetime1 == lifetime2

    def test_can_execute_commands_checks_status(self, aggregate: WorkspaceAggregate) -> None:
        """Test can_execute_commands property."""
        # New aggregate
        assert aggregate.can_execute_commands is False

        # After creation (CREATING)
        cmd = CreateWorkspaceCommand(execution_id="exec-123")
        aggregate.create_workspace(cmd)
        assert aggregate.can_execute_commands is False

        # After isolation started (READY)
        aggregate.record_isolation_started(
            isolation_id="container-123",
            isolation_type="docker",
        )
        assert aggregate.can_execute_commands is True


# =============================================================================
# EVENT SOURCING TESTS
# =============================================================================


class TestEventSourcing:
    """Tests for event sourcing behavior."""

    def test_uncommitted_events_captured(self, aggregate: WorkspaceAggregate) -> None:
        """Test that uncommitted events are captured."""
        cmd = CreateWorkspaceCommand(execution_id="exec-123")
        aggregate.create_workspace(cmd)

        events = list(aggregate._uncommitted_events)
        assert len(events) == 1
        assert events[0].event.event_type == "WorkspaceCreated"

    def test_multiple_events_captured(self, aggregate: WorkspaceAggregate) -> None:
        """Test that multiple events are captured in order."""
        # Create
        create_cmd = CreateWorkspaceCommand(execution_id="exec-123")
        aggregate.create_workspace(create_cmd)

        # Isolation started
        aggregate.record_isolation_started(
            isolation_id="container-123",
            isolation_type="docker",
        )

        # Inject tokens
        inject_cmd = InjectTokensCommand(
            workspace_id=str(aggregate.workspace_id),
            token_types=(TokenType.ANTHROPIC,),
        )
        aggregate.inject_tokens(inject_cmd)

        events = list(aggregate._uncommitted_events)
        assert len(events) == 3
        assert events[0].event.event_type == "WorkspaceCreated"
        assert events[1].event.event_type == "IsolationStarted"
        assert events[2].event.event_type == "TokensInjected"


@pytest.mark.unit
class TestBuildCommandEvent:
    def test_success_returns_executed_event(self) -> None:
        result = ExecutionResult(
            exit_code=0, success=True, duration_ms=150.0, stdout_lines=10, stderr_lines=0
        )
        event = _build_command_event("ws-1", ["echo", "hello"], result)
        assert isinstance(event, CommandExecutedEvent)
        assert event.workspace_id == "ws-1"
        assert event.command == ["echo", "hello"]
        assert event.exit_code == 0
        assert event.duration_ms == 150.0

    def test_failure_returns_failed_event(self) -> None:
        result = ExecutionResult(
            exit_code=1,
            success=False,
            duration_ms=50.0,
            stderr="Permission denied",
            timed_out=False,
        )
        event = _build_command_event("ws-1", ["rm", "/root"], result)
        assert isinstance(event, CommandFailedEvent)
        assert event.workspace_id == "ws-1"
        assert event.exit_code == 1
        assert event.error_message == "Permission denied"
        assert event.timed_out is False

    def test_long_stderr_truncated(self) -> None:
        long_stderr = "x" * 1000
        result = ExecutionResult(exit_code=1, success=False, duration_ms=10.0, stderr=long_stderr)
        event = _build_command_event("ws-1", ["bad-cmd"], result)
        assert isinstance(event, CommandFailedEvent)
        assert len(event.error_message) == 500
