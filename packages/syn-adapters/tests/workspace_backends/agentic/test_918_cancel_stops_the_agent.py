"""A CANCEL stops the agent through the operation it runs as (#918).

The agent in #918 ignored the signal it was sent, and the signal never reached
it anyway: ``interrupt()`` read a ``container_id`` the isolation handle never
had. The double here is that agent: its operation never completes on its own,
so the stream ends only if the provider is told to cancel it.

Driven through the real chain - ``EventStreamProcessor`` polling a controller,
``ManagedWorkspace.interrupt()``, ``AgenticEventStreamAdapter`` - with only the
provider replaced. The stream generator is held open on purpose: closing it
cancels the operation too, and a test that let it be collected could not tell
that path from the interrupt.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from agentic_isolation import WorkspaceConfig
from agentic_isolation.contract import (
    MISSING,
    ObservationPage,
    OperationRef,
    OperationSpec,
    OperationStatus,
    WorkspaceRef,
)
from agentic_isolation.providers.base import Workspace

from syn_adapters.control.commands import ControlSignal, ControlSignalType
from syn_adapters.workspace_backends.agentic.credentials import WorkspaceCredentials
from syn_adapters.workspace_backends.agentic.stream_adapter import AgenticEventStreamAdapter
from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationHandle,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)
from syn_shared.in_memory import InMemoryAdapter
from syn_shared.settings.session_store import SessionStoreSettings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.unit

_WS = WorkspaceRef(schema=MISSING, provider="recording", resource_id="ws-918")
_HANDLE = IsolationHandle(isolation_id="ws-918", isolation_type="docker")
_LINE = b'{"type":"system","subtype":"init"}\n'


class SignalIgnoringOperations(InMemoryAdapter):
    """An operation that keeps producing output until the provider cancels it.

    ``cancel`` is the provider's escalation (TERM, KILL, container stop), so it
    is the only thing that ends this workload. ``state_after_cancel`` models a
    provider that could not confirm the stop: still ``running``, or the
    terminal ``failed`` AW settles an unconfirmed cancel into.
    """

    def __init__(self, *, state_after_cancel: str = "cancelled", quiet: bool = False) -> None:
        super().__init__()
        self._state_after_cancel = state_after_cancel
        self._quiet = quiet
        self.spoke = asyncio.Event()
        self.state = "running"
        self.cancels: list[tuple[str, float]] = []

    async def start(self, workspace: Workspace, spec: OperationSpec) -> OperationRef:
        return OperationRef(workspace=_WS, operation_id="op-918", operation_key=spec.operation_key)

    async def observe(
        self, ref: OperationRef, *, cursor: str | None, max_bytes: int, wait_seconds: float = 0
    ) -> ObservationPage:
        index = int(cursor or 0)
        complete = self.state != "running"
        if self._quiet and index > 0 and not complete:
            # Says one line, then nothing: the provider's long poll comes back
            # empty, as the real one does after ``wait_seconds``.
            self.spoke.set()
            await asyncio.sleep(min(wait_seconds, 0.01))
            return ObservationPage(
                schema=MISSING,
                ref=ref,
                state="running",
                cursor=str(index),
                next_cursor=str(index),
                data_b64="",
                gap=MISSING,
                complete=False,
            )
        return ObservationPage(
            schema=MISSING,
            ref=ref,
            state=self.state,  # type: ignore[arg-type]
            cursor=str(index),
            next_cursor=str(index + 1),
            data_b64=base64.b64encode(b"" if complete else _LINE).decode(),
            gap=MISSING,
            complete=complete,
        )

    async def status(self, ref: OperationRef) -> OperationStatus:
        if self.state == "running":
            return OperationStatus(
                schema=MISSING, ref=ref, state="running", execution_id="ws-918", metadata={}
            )
        return OperationStatus(
            schema=MISSING,
            ref=ref,
            state=self.state,  # type: ignore[arg-type]
            exit_code=143,
            execution_id="ws-918",
            metadata={},
        )

    async def cancel(self, ref: OperationRef, *, grace_seconds: float) -> OperationStatus:
        self.cancels.append((ref.operation_id, grace_seconds))
        self.state = self._state_after_cancel
        return await self.status(ref)


class _Host:
    def __init__(self, operations: SignalIgnoringOperations) -> None:
        self.operations = operations
        self.credentials = WorkspaceCredentials(SessionStoreSettings())
        self.shares_host_kernel = True

    def workspace(self, isolation_id: str) -> Workspace | None:
        return Workspace(
            id=isolation_id,
            provider="recording",
            path=Path("/nonexistent"),
            config=WorkspaceConfig(),
        )


class _CancellingController:
    """Every poll answers CANCEL, as the controller does once a user cancels."""

    async def check_signal(self, execution_id: str) -> ControlSignal:
        return ControlSignal(
            signal_type=ControlSignalType.CANCEL, execution_id=execution_id, reason="user cancel"
        )


class _UserCancelsLater:
    """No signal until ``cancel()``; then CANCEL with no reason, as the API sends it."""

    def __init__(self) -> None:
        self.pending = False
        self.polls = 0

    def cancel(self) -> None:
        self.pending = True

    async def check_signal(self, execution_id: str) -> ControlSignal | None:
        self.polls += 1
        if not self.pending:
            return None
        return ControlSignal(signal_type=ControlSignalType.CANCEL, execution_id=execution_id)


def _workspace(ops: SignalIgnoringOperations) -> ManagedWorkspace:
    service = MagicMock()
    service._event_stream = AgenticEventStreamAdapter(_Host(ops))  # type: ignore[arg-type]
    return ManagedWorkspace(
        workspace_id="ws-918",
        execution_id="exec-918",
        aggregate=MagicMock(),
        isolation_handle=_HANDLE,
        sidecar_handle=None,
        _service=service,
    )


def _processor(controller: object | None = None) -> EventStreamProcessor:
    return EventStreamProcessor(
        tokens=TokenAccumulator(),
        subagents=SubagentTracker(),
        observability=None,
        controller=controller or _CancellingController(),  # type: ignore[arg-type]
        execution_id="exec-918",
        phase_id="phase-1",
        session_id="s-918",
        workspace_id="ws-918",
        agent_model=None,
    )


async def test_a_cancel_stops_an_agent_that_ignores_its_signals() -> None:
    ops = SignalIgnoringOperations()
    workspace = _workspace(ops)
    stream: AsyncIterator[str] = workspace.stream(["claude", "-p", "x"])
    try:
        async with asyncio.timeout(5):
            result = await _processor().process_stream(stream, workspace)

        assert result.interrupt_requested
        # Read before anything else is awaited: the held-open stream has not
        # been closed, so only interrupt() can have reached the provider.
        assert ops.cancels == [("op-918", 5.0)]
        assert ops.state == "cancelled"
    finally:
        await stream.aclose()  # type: ignore[attr-defined]


async def test_a_cancel_stops_an_agent_that_has_gone_quiet() -> None:
    """The verifier's B1 shape: one line, then silence, then a reasonless CANCEL.

    With polling tied to output, no further line meant no further poll at any
    elapsed time. The bound asserted is the poll interval plus slack, and the
    outer timeout only fails the test; it is not what stops the agent.
    """
    ops = SignalIgnoringOperations(quiet=True)
    workspace = _workspace(ops)
    controller = _UserCancelsLater()
    processor = _processor(controller)
    processor._cancel_poller.poll_seconds = 0.05
    stream: AsyncIterator[str] = workspace.stream(["claude", "-p", "x"])
    try:
        task = asyncio.create_task(processor.process_stream(stream, workspace))
        async with asyncio.timeout(5):
            await ops.spoke.wait()
            await asyncio.sleep(0.2)  # well past a poll: it is quiet, not stopped
            assert not task.done()
            assert ops.state == "running"
            controller.cancel()
            cancelled_at = asyncio.get_running_loop().time()
            result = await task
        took = asyncio.get_running_loop().time() - cancelled_at

        assert result.interrupt_requested
        assert result.interrupt_reason is None
        assert result.line_count == 1
        # First from interrupt(); closing the abandoned read may cancel again,
        # which the provider answers idempotently.
        assert ops.cancels[0] == ("op-918", 5.0)
        assert ops.state == "cancelled"
        assert took < 1.0, f"cancel took {took:.2f}s against a 0.05s poll"
    finally:
        await stream.aclose()  # type: ignore[attr-defined]


@pytest.mark.parametrize("state_after_cancel", ["running", "failed"])
async def test_interrupt_reports_a_stop_the_provider_could_not_confirm(
    state_after_cancel: str, caplog: pytest.LogCaptureFixture
) -> None:
    ops = SignalIgnoringOperations(state_after_cancel=state_after_cancel)
    workspace = _workspace(ops)
    stream = workspace.stream(["claude"])
    try:
        assert await stream.__anext__()  # type: ignore[attr-defined]
        with caplog.at_level(logging.ERROR):
            assert await workspace.interrupt() is False
        assert ops.cancels, "the provider was asked"
        assert "not confirmed stopped" in caplog.text
    finally:
        await stream.aclose()  # type: ignore[attr-defined]


async def test_interrupt_with_nothing_running_is_an_error_not_a_skip(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ops = SignalIgnoringOperations()
    with caplog.at_level(logging.ERROR):
        assert await _workspace(ops).interrupt() is False
    assert ops.cancels == []
    assert "no stream operation is running" in caplog.text


async def test_a_finished_stream_leaves_nothing_to_cancel() -> None:
    ops = SignalIgnoringOperations()
    workspace = _workspace(ops)
    stream = workspace.stream(["claude"])
    assert await stream.__anext__()  # type: ignore[attr-defined]
    ops.state = "succeeded"
    assert [line async for line in stream] == []
    assert await workspace.interrupt() is False
    assert ops.cancels == []
