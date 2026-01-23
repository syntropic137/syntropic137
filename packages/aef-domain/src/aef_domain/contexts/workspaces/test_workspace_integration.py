"""Integration tests for Workspace bounded context.

Tests the full workflow by composing:
- WorkspaceAggregate (domain)
- Memory adapters (infrastructure)

This validates:
1. DI/composability works correctly
2. Aggregate + adapters integrate properly
3. Full lifecycle: create -> inject -> execute -> terminate

Run: pytest packages/aef-domain/src/aef_domain/contexts/workspaces/test_workspace_integration.py -v
"""

from __future__ import annotations

import pytest

from aef_adapters.workspace_backends.memory import (
    MemoryEventStreamAdapter,
    MemoryIsolationAdapter,
    MemorySidecarAdapter,
    MemoryTokenInjectionAdapter,
)
from aef_domain.contexts.workspaces._shared.value_objects import (
    CapabilityType,
    ExecutionResult,
    IsolationBackendType,
    IsolationConfig,
    SecurityPolicy,
    TokenType,
    WorkspaceStatus,
)
from aef_domain.contexts.workspaces.domain.WorkspaceAggregate import WorkspaceAggregate
from aef_domain.contexts.workspaces.slices.create_workspace import CreateWorkspaceCommand
from aef_domain.contexts.workspaces.slices.execute_command import ExecuteCommandCommand
from aef_domain.contexts.workspaces.slices.inject_tokens import InjectTokensCommand
from aef_domain.contexts.workspaces.slices.terminate_workspace import TerminateWorkspaceCommand

# =============================================================================
# INTEGRATION TEST: Full Workspace Lifecycle
# =============================================================================


@pytest.mark.integration
class TestWorkspaceLifecycleIntegration:
    """Integration tests for full workspace lifecycle.

    Validates the architecture by composing real components:
    - WorkspaceAggregate handles commands and emits events
    - Memory adapters simulate infrastructure
    - Full flow: create -> inject tokens -> execute commands -> terminate
    """

    @pytest.fixture
    def isolation_adapter(self) -> MemoryIsolationAdapter:
        """Create isolation adapter."""
        return MemoryIsolationAdapter()

    @pytest.fixture
    def sidecar_adapter(self) -> MemorySidecarAdapter:
        """Create sidecar adapter."""
        return MemorySidecarAdapter()

    @pytest.fixture
    def token_adapter(self) -> MemoryTokenInjectionAdapter:
        """Create token injection adapter."""
        return MemoryTokenInjectionAdapter()

    @pytest.fixture
    def stream_adapter(self) -> MemoryEventStreamAdapter:
        """Create event stream adapter."""
        return MemoryEventStreamAdapter()

    @pytest.mark.asyncio
    async def test_full_lifecycle_create_execute_terminate(
        self,
        isolation_adapter: MemoryIsolationAdapter,
        sidecar_adapter: MemorySidecarAdapter,
        token_adapter: MemoryTokenInjectionAdapter,
    ) -> None:
        """Test complete workspace lifecycle: create -> execute -> terminate.

        This is the key integration test that validates:
        1. Aggregate can be created and handles commands
        2. Adapters can be called to perform operations
        3. Events are emitted correctly
        4. State transitions are correct
        """
        # === ARRANGE ===
        aggregate = WorkspaceAggregate()
        execution_id = "exec-integration-test-001"

        # === ACT: Step 1 - Create Workspace ===
        create_cmd = CreateWorkspaceCommand(
            execution_id=execution_id,
            workflow_id="wf-test",
            phase_id="phase-1",
            isolation_backend=IsolationBackendType.MEMORY,
            capabilities=(CapabilityType.NETWORK, CapabilityType.GIT),
            security_policy=SecurityPolicy(memory_limit_mb=512),
        )
        aggregate.create_workspace(create_cmd)

        # ASSERT: Aggregate in CREATING state
        assert aggregate.workspace_id is not None
        assert aggregate.status == WorkspaceStatus.CREATING
        assert aggregate.execution_id == execution_id

        # === ACT: Step 2 - Simulate Isolation Started (via adapter) ===
        config = IsolationConfig(
            execution_id=execution_id,
            workspace_id=str(aggregate.workspace_id),
            backend=IsolationBackendType.MEMORY,
        )
        isolation_handle = await isolation_adapter.create(config)

        # Record isolation started in aggregate
        aggregate.record_isolation_started(
            isolation_id=isolation_handle.isolation_id,
            isolation_type=isolation_handle.isolation_type,
            proxy_url="http://localhost:8080",  # Simulated sidecar
        )

        # ASSERT: Aggregate in READY state
        assert aggregate.status == WorkspaceStatus.READY
        assert aggregate.isolation_handle is not None
        assert aggregate.sidecar_enabled is True

        # === ACT: Step 3 - Inject Tokens ===
        inject_cmd = InjectTokensCommand(
            workspace_id=str(aggregate.workspace_id),
            token_types=(TokenType.ANTHROPIC, TokenType.GITHUB),
            ttl_seconds=300,
        )
        aggregate.inject_tokens(inject_cmd)

        # Also call adapter (in real code, this would happen in application layer)
        injection_result = await token_adapter.inject(
            isolation_handle,
            execution_id,
            [TokenType.ANTHROPIC, TokenType.GITHUB],
            ttl_seconds=300,
        )

        # ASSERT: Tokens injected
        assert injection_result.success is True
        assert TokenType.ANTHROPIC in aggregate.injected_tokens
        assert TokenType.GITHUB in aggregate.injected_tokens

        # === ACT: Step 4 - Execute Commands ===
        # Simulate command execution via adapter
        exec_result = await isolation_adapter.execute(
            isolation_handle,
            ["python", "-c", "print('Hello from workspace!')"],
        )

        # Record in aggregate
        exec_cmd = ExecuteCommandCommand(
            workspace_id=str(aggregate.workspace_id),
            command=["python", "-c", "print('Hello from workspace!')"],
            result=exec_result,
        )
        aggregate.execute_command(exec_cmd)

        # ASSERT: Command recorded
        assert aggregate.status == WorkspaceStatus.RUNNING
        assert aggregate.commands_executed == 1
        assert aggregate.commands_succeeded == 1

        # Execute another command
        exec_result2 = await isolation_adapter.execute(
            isolation_handle,
            ["echo", "Second command"],
        )
        exec_cmd2 = ExecuteCommandCommand(
            workspace_id=str(aggregate.workspace_id),
            command=["echo", "Second command"],
            result=exec_result2,
        )
        aggregate.execute_command(exec_cmd2)

        assert aggregate.commands_executed == 2

        # === ACT: Step 5 - Terminate Workspace ===
        terminate_cmd = TerminateWorkspaceCommand(
            workspace_id=str(aggregate.workspace_id),
            reason="completed",
        )
        aggregate.terminate_workspace(terminate_cmd)

        # Also destroy via adapter
        await isolation_adapter.destroy(isolation_handle)

        # ASSERT: Final state
        assert aggregate.status == WorkspaceStatus.DESTROYED
        assert aggregate.is_terminated is True
        assert aggregate.commands_executed == 2
        assert aggregate.terminated_at is not None

        # Adapter should report unhealthy after destroy
        assert await isolation_adapter.health_check(isolation_handle) is False

    @pytest.mark.asyncio
    async def test_lifecycle_with_command_failure(
        self,
        isolation_adapter: MemoryIsolationAdapter,
    ) -> None:
        """Test lifecycle handles command failures correctly."""
        # === ARRANGE ===
        aggregate = WorkspaceAggregate()

        # Create workspace
        aggregate.create_workspace(CreateWorkspaceCommand(execution_id="exec-fail-test"))

        config = IsolationConfig(
            execution_id="exec-fail-test",
            workspace_id=str(aggregate.workspace_id),
            backend=IsolationBackendType.MEMORY,
        )
        handle = await isolation_adapter.create(config)
        aggregate.record_isolation_started(
            isolation_id=handle.isolation_id,
            isolation_type=handle.isolation_type,
        )

        # === ACT: Execute a "failed" command ===
        # Simulate a failed execution
        failed_result = ExecutionResult(
            exit_code=1,
            success=False,
            duration_ms=100.0,
            stdout="",
            stderr="Error: command failed",
        )

        exec_cmd = ExecuteCommandCommand(
            workspace_id=str(aggregate.workspace_id),
            command=["bad-command"],
            result=failed_result,
        )
        aggregate.execute_command(exec_cmd)

        # === ASSERT ===
        assert aggregate.commands_executed == 1
        assert aggregate.commands_succeeded == 0
        assert aggregate.commands_failed == 1
        assert aggregate.status == WorkspaceStatus.RUNNING  # Still running, just failed cmd

    @pytest.mark.asyncio
    async def test_lifecycle_with_error_state(
        self,
        isolation_adapter: MemoryIsolationAdapter,
    ) -> None:
        """Test that errors transition workspace to ERROR state."""
        # === ARRANGE ===
        aggregate = WorkspaceAggregate()
        aggregate.create_workspace(CreateWorkspaceCommand(execution_id="exec-error-test"))

        # === ACT: Record an error ===
        aggregate.record_error(
            error_type="isolation_failure",
            error_message="Failed to start container: image not found",
            operation="create",
        )

        # === ASSERT ===
        assert aggregate.status == WorkspaceStatus.ERROR
        assert aggregate._metadata["last_error_type"] == "isolation_failure"

    @pytest.mark.asyncio
    async def test_event_sourcing_captures_all_events(
        self,
        isolation_adapter: MemoryIsolationAdapter,
        token_adapter: MemoryTokenInjectionAdapter,
    ) -> None:
        """Test that all operations emit events for event sourcing."""
        # === ARRANGE ===
        aggregate = WorkspaceAggregate()

        # === ACT: Perform operations ===
        aggregate.create_workspace(CreateWorkspaceCommand(execution_id="exec-events-test"))

        config = IsolationConfig(
            execution_id="exec-events-test",
            workspace_id=str(aggregate.workspace_id),
            backend=IsolationBackendType.MEMORY,
        )
        handle = await isolation_adapter.create(config)
        aggregate.record_isolation_started(
            isolation_id=handle.isolation_id,
            isolation_type="memory",
        )

        aggregate.inject_tokens(
            InjectTokensCommand(
                workspace_id=str(aggregate.workspace_id),
                token_types=(TokenType.ANTHROPIC,),
            )
        )

        result = await isolation_adapter.execute(handle, ["echo", "test"])
        aggregate.execute_command(
            ExecuteCommandCommand(
                workspace_id=str(aggregate.workspace_id),
                command=["echo", "test"],
                result=result,
            )
        )

        aggregate.terminate_workspace(
            TerminateWorkspaceCommand(
                workspace_id=str(aggregate.workspace_id),
                reason="completed",
            )
        )

        # === ASSERT: Check events ===
        events = list(aggregate._uncommitted_events)
        event_types = [e.event.event_type for e in events]

        assert len(events) == 5
        assert "WorkspaceCreated" in event_types
        assert "IsolationStarted" in event_types
        assert "TokensInjected" in event_types
        assert "CommandExecuted" in event_types
        assert "WorkspaceTerminated" in event_types

    @pytest.mark.asyncio
    async def test_stream_adapter_integration(
        self,
        isolation_adapter: MemoryIsolationAdapter,
        stream_adapter: MemoryEventStreamAdapter,
    ) -> None:
        """Test event streaming adapter integration."""
        # === ARRANGE ===
        config = IsolationConfig(
            execution_id="exec-stream-test",
            workspace_id="ws-stream",
            backend=IsolationBackendType.MEMORY,
        )
        handle = await isolation_adapter.create(config)

        # Configure mock stream output
        stream_adapter.set_stream_output(
            handle,
            [
                '{"type": "start", "task": "test"}',
                '{"type": "tool_use", "tool": "read_file"}',
                '{"type": "result", "output": "success"}',
            ],
        )

        # === ACT: Stream events ===
        lines = [line async for line in stream_adapter.stream(handle, ["agent", "run"])]

        # === ASSERT ===
        assert len(lines) == 3
        assert "start" in lines[0]
        assert "tool_use" in lines[1]
        assert "result" in lines[2]


# =============================================================================
# INTEGRATION TEST: DI Composition
# =============================================================================


class TestDIComposition:
    """Tests that validate DI composition patterns work correctly."""

    @pytest.mark.asyncio
    async def test_adapters_are_independent(self) -> None:
        """Test that adapters can be created independently."""
        # Each adapter should work independently
        isolation = MemoryIsolationAdapter()
        sidecar = MemorySidecarAdapter()
        token = MemoryTokenInjectionAdapter()
        stream = MemoryEventStreamAdapter()

        # Should all be usable
        assert isolation is not None
        assert sidecar is not None
        assert token is not None
        assert stream is not None

    @pytest.mark.asyncio
    async def test_aggregate_is_infrastructure_agnostic(self) -> None:
        """Test that aggregate has no knowledge of adapters."""
        aggregate = WorkspaceAggregate()

        # Aggregate should work without any adapters
        aggregate.create_workspace(CreateWorkspaceCommand(execution_id="exec-agnostic"))

        # Should be able to record events without calling adapters
        aggregate.record_isolation_started(
            isolation_id="fake-id",
            isolation_type="mock",
        )

        assert aggregate.status == WorkspaceStatus.READY

    @pytest.mark.asyncio
    async def test_multiple_workspaces_independent(
        self,
    ) -> None:
        """Test that multiple workspaces are independent."""
        adapter = MemoryIsolationAdapter()

        # Create two workspaces
        agg1 = WorkspaceAggregate()
        agg1.create_workspace(CreateWorkspaceCommand(execution_id="exec-1"))

        agg2 = WorkspaceAggregate()
        agg2.create_workspace(CreateWorkspaceCommand(execution_id="exec-2"))

        # Create isolation for both
        handle1 = await adapter.create(
            IsolationConfig(
                execution_id="exec-1",
                workspace_id=str(agg1.workspace_id),
                backend=IsolationBackendType.MEMORY,
            )
        )
        handle2 = await adapter.create(
            IsolationConfig(
                execution_id="exec-2",
                workspace_id=str(agg2.workspace_id),
                backend=IsolationBackendType.MEMORY,
            )
        )

        # Execute in workspace 1
        result1 = await adapter.execute(handle1, ["cmd1"])
        agg1.record_isolation_started(handle1.isolation_id, "memory")
        agg1.execute_command(
            ExecuteCommandCommand(
                workspace_id=str(agg1.workspace_id),
                command=["cmd1"],
                result=result1,
            )
        )

        # Workspace 2 should be unaffected
        assert agg1.commands_executed == 1
        assert agg2.commands_executed == 0

        # Terminate workspace 1
        agg1.terminate_workspace(
            TerminateWorkspaceCommand(
                workspace_id=str(agg1.workspace_id),
                reason="completed",
            )
        )
        await adapter.destroy(handle1)

        # Workspace 2 should still be healthy
        assert agg1.is_terminated is True
        assert agg2.is_terminated is False
        assert await adapter.health_check(handle2) is True
