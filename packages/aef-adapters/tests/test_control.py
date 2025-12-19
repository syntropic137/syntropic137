"""Tests for control plane core components."""

from __future__ import annotations

import pytest

from aef_adapters.control import (
    CancelExecution,
    ControlSignalType,
    ExecutionController,
    ExecutionState,
    ExecutionStateMachine,
    InjectContext,
    InvalidTransitionError,
    PauseExecution,
    ResumeExecution,
)
from aef_adapters.control.adapters.memory import (
    InMemoryControlStateAdapter,
    InMemorySignalQueueAdapter,
)


@pytest.mark.unit
class TestExecutionStateMachine:
    """Tests for ExecutionStateMachine."""

    def test_initial_state_is_pending(self) -> None:
        """New state machine starts in PENDING state."""
        sm = ExecutionStateMachine()
        assert sm.state == ExecutionState.PENDING

    def test_can_start_with_custom_state(self) -> None:
        """State machine can be initialized with a specific state."""
        sm = ExecutionStateMachine(ExecutionState.RUNNING)
        assert sm.state == ExecutionState.RUNNING

    def test_valid_transition_pending_to_running(self) -> None:
        """Can transition from PENDING to RUNNING."""
        sm = ExecutionStateMachine()
        assert sm.can_transition_to(ExecutionState.RUNNING)
        sm.transition(ExecutionState.RUNNING)
        assert sm.state == ExecutionState.RUNNING

    def test_valid_transition_running_to_paused(self) -> None:
        """Can transition from RUNNING to PAUSED."""
        sm = ExecutionStateMachine(ExecutionState.RUNNING)
        assert sm.can_pause()
        sm.transition(ExecutionState.PAUSED)
        assert sm.state == ExecutionState.PAUSED

    def test_valid_transition_paused_to_running(self) -> None:
        """Can transition from PAUSED to RUNNING (resume)."""
        sm = ExecutionStateMachine(ExecutionState.PAUSED)
        assert sm.can_resume()
        sm.transition(ExecutionState.RUNNING)
        assert sm.state == ExecutionState.RUNNING

    def test_valid_transition_running_to_cancelled(self) -> None:
        """Can transition from RUNNING to CANCELLED."""
        sm = ExecutionStateMachine(ExecutionState.RUNNING)
        assert sm.can_cancel()
        sm.transition(ExecutionState.CANCELLED)
        assert sm.state == ExecutionState.CANCELLED

    def test_invalid_transition_raises_error(self) -> None:
        """Invalid transitions raise InvalidTransitionError."""
        sm = ExecutionStateMachine(ExecutionState.PENDING)
        with pytest.raises(InvalidTransitionError):
            sm.transition(ExecutionState.PAUSED)  # Can't pause from PENDING

    def test_terminal_state_completed(self) -> None:
        """COMPLETED is a terminal state."""
        sm = ExecutionStateMachine(ExecutionState.COMPLETED)
        assert sm.is_terminal
        assert not sm.can_transition_to(ExecutionState.RUNNING)

    def test_terminal_state_cancelled(self) -> None:
        """CANCELLED is a terminal state."""
        sm = ExecutionStateMachine(ExecutionState.CANCELLED)
        assert sm.is_terminal
        assert not sm.can_cancel()  # Can't cancel again

    def test_terminal_state_failed(self) -> None:
        """FAILED is a terminal state."""
        sm = ExecutionStateMachine(ExecutionState.FAILED)
        assert sm.is_terminal

    def test_cannot_resume_from_non_paused_state(self) -> None:
        """Can only resume from PAUSED state."""
        sm = ExecutionStateMachine(ExecutionState.RUNNING)
        assert not sm.can_resume()


class TestExecutionController:
    """Tests for ExecutionController."""

    @pytest.fixture
    def state_adapter(self) -> InMemoryControlStateAdapter:
        return InMemoryControlStateAdapter()

    @pytest.fixture
    def signal_adapter(self) -> InMemorySignalQueueAdapter:
        return InMemorySignalQueueAdapter()

    @pytest.fixture
    def controller(
        self, state_adapter: InMemoryControlStateAdapter, signal_adapter: InMemorySignalQueueAdapter
    ) -> ExecutionController:
        return ExecutionController(state_adapter, signal_adapter)

    @pytest.mark.asyncio
    async def test_pause_running_execution(
        self, controller: ExecutionController, signal_adapter: InMemorySignalQueueAdapter
    ) -> None:
        """Can pause a running execution."""
        execution_id = "test-exec-1"
        await controller.initialize_execution(execution_id, ExecutionState.RUNNING)

        cmd = PauseExecution(execution_id=execution_id, reason="User requested")
        result = await controller.handle_command(cmd)

        assert result.success
        assert result.message == "Pause signal queued"

        # Check signal was queued
        signal = await signal_adapter.dequeue(execution_id)
        assert signal is not None
        assert signal.signal_type == ControlSignalType.PAUSE
        assert signal.reason == "User requested"

    @pytest.mark.asyncio
    async def test_cannot_pause_paused_execution(self, controller: ExecutionController) -> None:
        """Cannot pause an already paused execution."""
        execution_id = "test-exec-2"
        await controller.initialize_execution(execution_id, ExecutionState.PAUSED)

        cmd = PauseExecution(execution_id=execution_id)
        result = await controller.handle_command(cmd)

        assert not result.success
        assert "Cannot pause" in (result.error or "")

    @pytest.mark.asyncio
    async def test_resume_paused_execution(
        self, controller: ExecutionController, signal_adapter: InMemorySignalQueueAdapter
    ) -> None:
        """Can resume a paused execution."""
        execution_id = "test-exec-3"
        await controller.initialize_execution(execution_id, ExecutionState.PAUSED)

        cmd = ResumeExecution(execution_id=execution_id)
        result = await controller.handle_command(cmd)

        assert result.success
        assert result.message == "Resume signal queued"

        # Check signal was queued
        signal = await signal_adapter.dequeue(execution_id)
        assert signal is not None
        assert signal.signal_type == ControlSignalType.RESUME

    @pytest.mark.asyncio
    async def test_cannot_resume_running_execution(self, controller: ExecutionController) -> None:
        """Cannot resume a running execution."""
        execution_id = "test-exec-4"
        await controller.initialize_execution(execution_id, ExecutionState.RUNNING)

        cmd = ResumeExecution(execution_id=execution_id)
        result = await controller.handle_command(cmd)

        assert not result.success
        assert "Cannot resume" in (result.error or "")

    @pytest.mark.asyncio
    async def test_cancel_running_execution(
        self, controller: ExecutionController, signal_adapter: InMemorySignalQueueAdapter
    ) -> None:
        """Can cancel a running execution."""
        execution_id = "test-exec-5"
        await controller.initialize_execution(execution_id, ExecutionState.RUNNING)

        cmd = CancelExecution(execution_id=execution_id, reason="Timed out")
        result = await controller.handle_command(cmd)

        assert result.success
        assert result.message == "Cancel signal queued"

        # Check signal was queued
        signal = await signal_adapter.dequeue(execution_id)
        assert signal is not None
        assert signal.signal_type == ControlSignalType.CANCEL
        assert signal.reason == "Timed out"

    @pytest.mark.asyncio
    async def test_cancel_paused_execution(self, controller: ExecutionController) -> None:
        """Can cancel a paused execution."""
        execution_id = "test-exec-6"
        await controller.initialize_execution(execution_id, ExecutionState.PAUSED)

        cmd = CancelExecution(execution_id=execution_id)
        result = await controller.handle_command(cmd)

        assert result.success

    @pytest.mark.asyncio
    async def test_cannot_cancel_completed_execution(self, controller: ExecutionController) -> None:
        """Cannot cancel a completed execution."""
        execution_id = "test-exec-7"
        await controller.initialize_execution(execution_id, ExecutionState.COMPLETED)

        cmd = CancelExecution(execution_id=execution_id)
        result = await controller.handle_command(cmd)

        assert not result.success
        assert "Cannot cancel" in (result.error or "")

    @pytest.mark.asyncio
    async def test_inject_into_running_execution(
        self, controller: ExecutionController, signal_adapter: InMemorySignalQueueAdapter
    ) -> None:
        """Can inject context into a running execution."""
        execution_id = "test-exec-8"
        await controller.initialize_execution(execution_id, ExecutionState.RUNNING)

        cmd = InjectContext(execution_id=execution_id, message="New instructions", role="user")
        result = await controller.handle_command(cmd)

        assert result.success
        assert result.message == "Context injection queued"

        # Check signal was queued
        signal = await signal_adapter.dequeue(execution_id)
        assert signal is not None
        assert signal.signal_type == ControlSignalType.INJECT
        assert signal.inject_message == "New instructions"

    @pytest.mark.asyncio
    async def test_cannot_inject_into_terminal_execution(
        self, controller: ExecutionController
    ) -> None:
        """Cannot inject into a terminal execution."""
        execution_id = "test-exec-9"
        await controller.initialize_execution(execution_id, ExecutionState.COMPLETED)

        cmd = InjectContext(execution_id=execution_id, message="Too late")
        result = await controller.handle_command(cmd)

        assert not result.success
        assert "terminal" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_acknowledge_state_transition(
        self, controller: ExecutionController, state_adapter: InMemoryControlStateAdapter
    ) -> None:
        """Executor can acknowledge state transitions."""
        execution_id = "test-exec-10"
        await controller.initialize_execution(execution_id, ExecutionState.RUNNING)

        # Acknowledge transition to PAUSED
        await controller.acknowledge_state(execution_id, ExecutionState.PAUSED)

        state = await controller.get_state(execution_id)
        assert state == ExecutionState.PAUSED

        # Verify persisted
        persisted_state = await state_adapter.get_state(execution_id)
        assert persisted_state == ExecutionState.PAUSED

    @pytest.mark.asyncio
    async def test_get_state(self, controller: ExecutionController) -> None:
        """Can get current state for an execution."""
        execution_id = "test-exec-11"
        await controller.initialize_execution(execution_id, ExecutionState.RUNNING)

        state = await controller.get_state(execution_id)
        assert state == ExecutionState.RUNNING

    @pytest.mark.asyncio
    async def test_check_signal(self, controller: ExecutionController) -> None:
        """Can check for pending signals."""
        execution_id = "test-exec-12"
        await controller.initialize_execution(execution_id, ExecutionState.RUNNING)

        # No signals initially
        signal = await controller.check_signal(execution_id)
        assert signal is None

        # Send pause command
        cmd = PauseExecution(execution_id=execution_id)
        await controller.handle_command(cmd)

        # Now there should be a signal
        signal = await controller.check_signal(execution_id)
        assert signal is not None
        assert signal.signal_type == ControlSignalType.PAUSE

        # Signal should be consumed
        signal = await controller.check_signal(execution_id)
        assert signal is None


class TestInMemoryAdapters:
    """Tests for in-memory adapter implementations."""

    @pytest.mark.asyncio
    async def test_state_adapter_save_and_get(self) -> None:
        """State adapter can save and retrieve state."""
        adapter = InMemoryControlStateAdapter()

        await adapter.save_state("exec-1", ExecutionState.RUNNING)
        state = await adapter.get_state("exec-1")

        assert state == ExecutionState.RUNNING

    @pytest.mark.asyncio
    async def test_state_adapter_returns_none_for_unknown(self) -> None:
        """State adapter returns None for unknown execution."""
        adapter = InMemoryControlStateAdapter()

        state = await adapter.get_state("unknown")
        assert state is None

    @pytest.mark.asyncio
    async def test_signal_adapter_fifo_order(self) -> None:
        """Signal adapter maintains FIFO order."""
        from aef_adapters.control.commands import ControlSignal

        adapter = InMemorySignalQueueAdapter()
        execution_id = "exec-1"

        signal1 = ControlSignal(ControlSignalType.PAUSE, execution_id)
        signal2 = ControlSignal(ControlSignalType.RESUME, execution_id)

        await adapter.enqueue(execution_id, signal1)
        await adapter.enqueue(execution_id, signal2)

        result1 = await adapter.dequeue(execution_id)
        result2 = await adapter.dequeue(execution_id)
        result3 = await adapter.dequeue(execution_id)

        assert result1 is not None
        assert result1.signal_type == ControlSignalType.PAUSE
        assert result2 is not None
        assert result2.signal_type == ControlSignalType.RESUME
        assert result3 is None
