"""Tests for CancelSignalPoller."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.CancelSignalPoller import (
    CancelSignalPoller,
    PollResult,
)


def _make_cancel_signal(reason: str = "User stopped"):
    """Create a ControlSignal with CANCEL type."""
    from syn_adapters.control.commands import ControlSignal, ControlSignalType

    return ControlSignal(
        signal_type=ControlSignalType.CANCEL,
        execution_id="exec-1",
        reason=reason,
    )


@pytest.mark.unit
class TestCancelSignalPoller:
    @pytest.mark.asyncio
    async def test_no_controller_returns_no_interrupt(self) -> None:
        poller = CancelSignalPoller(controller=None, execution_id="exec-1")
        result = await poller.check(10)
        assert result == PollResult(should_interrupt=False)

    @pytest.mark.asyncio
    async def test_non_boundary_line_returns_no_interrupt(self) -> None:
        controller = MagicMock()
        controller.check_signal = AsyncMock(return_value=None)
        poller = CancelSignalPoller(controller=controller, execution_id="exec-1")
        result = await poller.check(7)
        assert result == PollResult(should_interrupt=False)
        controller.check_signal.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_signal_at_boundary(self) -> None:
        controller = MagicMock()
        controller.check_signal = AsyncMock(return_value=_make_cancel_signal("test reason"))
        poller = CancelSignalPoller(controller=controller, execution_id="exec-1")
        result = await poller.check(10)
        assert result.should_interrupt is True
        assert result.reason == "test reason"

    @pytest.mark.asyncio
    async def test_non_cancel_signal_ignored(self) -> None:
        from syn_adapters.control.commands import ControlSignal, ControlSignalType

        signal = ControlSignal(
            signal_type=ControlSignalType.PAUSE,
            execution_id="exec-1",
            reason="pause",
        )
        controller = MagicMock()
        controller.check_signal = AsyncMock(return_value=signal)
        poller = CancelSignalPoller(controller=controller, execution_id="exec-1")
        result = await poller.check(10)
        assert result.should_interrupt is False

    @pytest.mark.asyncio
    async def test_custom_poll_interval(self) -> None:
        controller = MagicMock()
        controller.check_signal = AsyncMock(return_value=_make_cancel_signal())
        poller = CancelSignalPoller(controller=controller, execution_id="exec-1", poll_interval=5)
        # Line 5 should trigger (custom interval)
        result = await poller.check(5)
        assert result.should_interrupt is True
        # Line 7 should not trigger
        result = await poller.check(7)
        assert result == PollResult(should_interrupt=False)
