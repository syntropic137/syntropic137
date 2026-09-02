"""HTTP-layer tests for execution control endpoints (#1062).

Covers the hop that #1062 identified as broken: the domain
`ExecutionController` reads state, enqueues an async cancel/pause/resume
signal, and returns the state it read *before* enqueuing. That value then
flows through two more constructors (`syn_api.types.ControlResult` and
`ControlResponse`) before it reaches an HTTP client. These tests exercise
that full chain rather than asserting on the object edited directly, so a
value that is computed correctly but dropped or renamed at either
downstream constructor is caught.
"""

from __future__ import annotations

import pytest

from syn_adapters.control.commands import ControlCommand
from syn_adapters.control.commands import ControlResult as DomainControlResult
from syn_api.routes.executions.control import (
    ControlResponse,
    _handle_control_result,
    cancel,
)
from syn_api.types import Err


class _StubController:
    """Stand-in for ExecutionController that returns a canned domain result."""

    def __init__(self, domain_result: DomainControlResult) -> None:
        self._domain_result = domain_result
        self.received_commands: list[ControlCommand] = []

    async def handle_command(self, cmd: ControlCommand) -> DomainControlResult:
        self.received_commands.append(cmd)
        return self._domain_result


@pytest.mark.asyncio
async def test_cancel_response_does_not_assert_unconfirmed_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful cancel enqueues a signal but has not observed the
    transition yet. The HTTP response must not present the pre-enqueue
    read as a confirmed post-cancel state.
    """
    domain_result = DomainControlResult(
        success=True,
        execution_id="exec-1",
        new_state="running",  # state read BEFORE the cancel signal was enqueued
        message="Cancel signal queued",
        state_pending=True,
    )
    stub = _StubController(domain_result)
    monkeypatch.setattr("syn_api.routes.executions.control.get_controller", lambda: stub)

    result = await cancel("exec-1", reason="timed out")
    assert not isinstance(result, Err)
    ctrl = result.value

    # The hop under test: does state_pending survive the domain -> API ControlResult mapping?
    assert ctrl.state_pending is True

    response: ControlResponse = await _handle_control_result(result, "cancel")

    # The hop under test: does state_pending survive the ControlResult -> ControlResponse mapping?
    assert response.state_pending is True
    assert response.state == "running"
    assert response.success is True


@pytest.mark.asyncio
async def test_cancel_response_reports_confirmed_state_when_no_signal_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When cancellation is rejected (nothing enqueued), the read state is
    the actual current state, not a claim about a future transition -
    state_pending must be False.
    """
    domain_result = DomainControlResult(
        success=False,
        execution_id="exec-2",
        new_state="completed",
        error="Cannot cancel execution in state completed",
        state_pending=False,
    )
    stub = _StubController(domain_result)
    monkeypatch.setattr("syn_api.routes.executions.control.get_controller", lambda: stub)

    result = await cancel("exec-2")
    assert not isinstance(result, Err)
    ctrl = result.value
    assert ctrl.state_pending is False
