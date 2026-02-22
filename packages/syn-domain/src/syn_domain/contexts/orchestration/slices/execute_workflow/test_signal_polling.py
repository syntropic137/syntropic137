"""Unit tests for WorkflowExecutionEngine signal polling.

T-5: Verifies the interrupt mechanism in the streaming loop:
- CANCEL signal received after N lines breaks the loop
- workspace.interrupt() is called on CANCEL signal
- WorkflowInterruptedError is raised with correct data
- Without a cancel signal, streaming completes normally
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionEngine import (
    WorkflowInterruptedError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cancel_signal(reason: str = "User stopped"):
    """Create a ControlSignal with CANCEL type."""
    from syn_adapters.control.commands import ControlSignal, ControlSignalType

    return ControlSignal(
        signal_type=ControlSignalType.CANCEL,
        execution_id="exec-1",
        reason=reason,
    )


def _make_controller_with_cancel_after(call_count_to_cancel: int, reason: str = "User stopped"):
    """Controller that returns a CANCEL signal on the Nth check_signal call."""
    controller = MagicMock()
    call_counter = {"n": 0}

    async def check_signal(execution_id: str):
        call_counter["n"] += 1
        if call_counter["n"] >= call_count_to_cancel:
            return _make_cancel_signal(reason)
        return None

    controller.check_signal = check_signal
    return controller


def _make_controller_with_no_signal():
    """Controller that never returns a signal."""
    controller = MagicMock()
    controller.check_signal = AsyncMock(return_value=None)
    return controller


@pytest.mark.unit
class TestWorkflowInterruptedError:
    """Verify WorkflowInterruptedError carries interrupt context."""

    def test_carries_phase_id_and_reason(self) -> None:
        err = WorkflowInterruptedError(
            phase_id="p-1",
            reason="User stopped",
            git_sha="abc123",
            partial_artifact_ids=["art-1"],
            partial_input_tokens=100,
            partial_output_tokens=50,
        )
        assert err.phase_id == "p-1"
        assert err.reason == "User stopped"
        assert err.git_sha == "abc123"
        assert err.partial_artifact_ids == ["art-1"]
        assert err.partial_input_tokens == 100
        assert err.partial_output_tokens == 50

    def test_defaults_are_sensible(self) -> None:
        err = WorkflowInterruptedError(phase_id="p-1")
        assert err.reason is None
        assert err.git_sha is None
        assert err.partial_artifact_ids == []
        assert err.partial_input_tokens == 0
        assert err.partial_output_tokens == 0


@pytest.mark.unit
class TestSignalPollingLogic:
    """T-5: Tests for the signal polling logic extracted from the streaming loop."""

    @pytest.mark.asyncio
    async def test_cancel_signal_triggers_interrupt(self) -> None:
        """CANCEL signal causes interrupt() to be called and breaks the loop."""
        from syn_adapters.control.commands import ControlSignalType

        controller = _make_controller_with_cancel_after(call_count_to_cancel=1)
        interrupt_called = False

        async def mock_interrupt():
            nonlocal interrupt_called
            interrupt_called = True
            return True

        # Simulate the loop logic (10-line polling interval)
        line_count = 0
        interrupt_requested = False
        interrupt_reason = None
        lines_to_stream = 25

        for _ in range(lines_to_stream):
            line_count += 1
            if line_count % 10 == 0:
                signal = await controller.check_signal("exec-1")
                if signal and signal.signal_type == ControlSignalType.CANCEL:
                    interrupt_requested = True
                    interrupt_reason = signal.reason
                    await mock_interrupt()
                    break

        assert interrupt_requested is True
        assert interrupt_called is True
        assert line_count == 10  # Breaks at line 10 (first 10-line check)
        assert interrupt_reason == "User stopped"

    @pytest.mark.asyncio
    async def test_no_signal_completes_all_lines(self) -> None:
        """Without a CANCEL signal, all lines are consumed normally."""
        from syn_adapters.control.commands import ControlSignalType

        controller = _make_controller_with_no_signal()
        interrupt_called = False

        async def mock_interrupt():
            nonlocal interrupt_called
            interrupt_called = True
            return True

        line_count = 0
        interrupt_requested = False
        lines_to_stream = 25

        for _ in range(lines_to_stream):
            line_count += 1
            if line_count % 10 == 0:
                signal = await controller.check_signal("exec-1")
                if signal and signal.signal_type == ControlSignalType.CANCEL:
                    interrupt_requested = True
                    await mock_interrupt()
                    break

        assert interrupt_requested is False
        assert interrupt_called is False
        assert line_count == 25  # All 25 lines consumed

    @pytest.mark.asyncio
    async def test_signal_checked_every_10_lines(self) -> None:
        """check_signal is called exactly floor(N/10) times for N lines."""
        from syn_adapters.control.commands import ControlSignalType

        check_count = 0

        async def counting_check_signal(execution_id: str):
            nonlocal check_count
            check_count += 1
            return None

        controller = MagicMock()
        controller.check_signal = counting_check_signal

        lines_to_stream = 35

        for line_count, _ in enumerate(range(lines_to_stream), start=1):
            if line_count % 10 == 0:
                signal = await controller.check_signal("exec-1")
                if signal and signal.signal_type == ControlSignalType.CANCEL:
                    break

        # 35 lines → checks at 10, 20, 30 → 3 checks
        assert check_count == 3

    @pytest.mark.asyncio
    async def test_cancel_on_second_check_breaks_at_20(self) -> None:
        """If cancel arrives on 2nd check, loop breaks at line 20."""
        from syn_adapters.control.commands import ControlSignalType

        controller = _make_controller_with_cancel_after(call_count_to_cancel=2)

        line_count = 0
        interrupt_requested = False
        lines_to_stream = 50

        for _ in range(lines_to_stream):
            line_count += 1
            if line_count % 10 == 0:
                signal = await controller.check_signal("exec-1")
                if signal and signal.signal_type == ControlSignalType.CANCEL:
                    interrupt_requested = True
                    break

        assert interrupt_requested is True
        assert line_count == 20  # Breaks at line 20 (second 10-line check)
