"""Tests for control plane core components."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.grpc_client import GrpcEventStoreClient
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.control import (
    CancelExecution,
    ControlCommand,
    ControlSignalType,
    ExecutionController,
    InjectContext,
)
from syn_adapters.control.adapters.memory import InMemorySignalQueueAdapter
from syn_adapters.control.adapters.redis_adapter import RedisSignalQueueAdapter
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    CancelExecutionCommand,
    CompleteExecutionCommand,
    FailExecutionCommand,
    InterruptExecutionCommand,
    StartExecutionCommand,
    StartPhaseCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
    FailureClassification,
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)

pytestmark = pytest.mark.unit

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from event_sourcing import EventStoreClient


# =============================================================================
# Executions recorded through the real aggregate and a real event stream. The
# controller is handed nothing else: whatever it admits, it admits on the
# aggregate's word.
# =============================================================================


def _executions(
    client: EventStoreClient | None = None,
) -> RepositoryAdapter[WorkflowExecutionAggregate]:
    return RepositoryAdapter(
        EventStoreRepository(
            client or MemoryEventStoreClient(),
            WorkflowExecutionAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "WorkflowExecution",
        )
    )


def _cancel(agg: WorkflowExecutionAggregate) -> None:
    agg.cancel_execution(CancelExecutionCommand(execution_id=agg.id or "", phase_id="p1"))


def _complete(agg: WorkflowExecutionAggregate) -> None:
    agg.complete_execution(
        CompleteExecutionCommand(
            execution_id=agg.id or "",
            completed_phases=1,
            total_phases=1,
            total_input_tokens=0,
            total_output_tokens=0,
            total_cache_creation_tokens=0,
            total_cache_read_tokens=0,
            duration_seconds=1.0,
            artifact_ids=[],
        )
    )


def _fail(agg: WorkflowExecutionAggregate) -> None:
    agg.fail_execution(
        FailExecutionCommand(
            execution_id=agg.id or "",
            error="boom",
            error_type=None,
            failed_phase_id="p1",
            completed_phases=0,
            total_phases=1,
            classification=FailureClassification.UNCLASSIFIED,
        )
    )


def _interrupt(agg: WorkflowExecutionAggregate) -> None:
    agg.interrupt_execution(InterruptExecutionCommand(execution_id=agg.id or "", phase_id="p1"))


#: How to bring a started execution to each status an execution can be loaded in.
_TO_STATUS: dict[ExecutionStatus, Callable[[WorkflowExecutionAggregate], None] | None] = {
    ExecutionStatus.RUNNING: None,
    ExecutionStatus.CANCELLED: _cancel,
    ExecutionStatus.COMPLETED: _complete,
    ExecutionStatus.FAILED: _fail,
    ExecutionStatus.INTERRUPTED: _interrupt,
}


async def _record(
    executions: RepositoryAdapter[WorkflowExecutionAggregate],
    execution_id: str,
    status: ExecutionStatus,
) -> None:
    """Write an execution's stream so that, rehydrated, it is in `status`."""
    agg = WorkflowExecutionAggregate()
    agg.start_execution(
        StartExecutionCommand(
            execution_id=execution_id,
            workflow_id="wf",
            workflow_name="W",
            total_phases=1,
            inputs={"task": "t"},
            phase_definitions=[PhaseDefinition(phase_id="p1", name="P1", order=1)],
        )
    )
    agg.start_phase(
        StartPhaseCommand(
            execution_id=execution_id,
            workflow_id="wf",
            phase_id="p1",
            phase_name="P1",
            phase_order=1,
        )
    )
    step = _TO_STATUS[status]
    if step is not None:
        step(agg)
    await executions.save_new(agg)

    loaded = await executions.get_by_id(execution_id)
    assert loaded is not None
    assert loaded.status is status  # the precondition really holds, from the stream


_REQUESTS: dict[ControlSignalType, Callable[[str], ControlCommand]] = {
    ControlSignalType.CANCEL: lambda eid: CancelExecution(execution_id=eid, reason="r"),
    ControlSignalType.INJECT: lambda eid: InjectContext(execution_id=eid, message="m"),
}


def _aggregate_command_accepted(agg: WorkflowExecutionAggregate, signal: ControlSignalType) -> bool:
    """What the aggregate's own command handler does with the same request."""
    eid = agg.id or ""
    commands: dict[ControlSignalType, Callable[[], None]] = {
        ControlSignalType.CANCEL: lambda: agg.cancel_execution(
            CancelExecutionCommand(execution_id=eid, phase_id="p1")
        ),
    }
    try:
        commands[signal]()
    except ValueError:
        return False
    return True


@pytest.mark.unit
class TestAdmissionIsTheAggregatesDecision:
    """ADR-014 section 7, fail-open 1: the controller must not decide on its own.

    Before, it ran a private state machine over the execution detail projection,
    so its answer could differ from the aggregate's whenever the projection
    lagged. These tests hand it only an event stream, so there is nothing else
    for it to be right about.
    """

    @pytest.mark.parametrize("status", list(_TO_STATUS))
    @pytest.mark.parametrize("signal", [ControlSignalType.CANCEL])
    async def test_the_operator_gets_the_answer_the_command_will_get(
        self, status: ExecutionStatus, signal: ControlSignalType
    ) -> None:
        executions = _executions()
        signals = InMemorySignalQueueAdapter()
        await _record(executions, "exec-1", status)
        agg = await executions.get_by_id("exec-1")
        assert agg is not None
        expected = _aggregate_command_accepted(agg, signal)

        result = await ExecutionController(executions, signals).handle_command(
            _REQUESTS[signal]("exec-1")
        )

        assert result.success is expected
        assert result.new_state == status.value
        queued = await signals.get_signal("exec-1")
        assert (queued is not None) is expected

    async def test_a_cancelled_execution_refuses_every_request(self) -> None:
        """EXP4's measurement, now through the controller: nothing is queued."""
        executions = _executions()
        signals = InMemorySignalQueueAdapter()
        await _record(executions, "exec-c", ExecutionStatus.CANCELLED)
        controller = ExecutionController(executions, signals)

        for signal, request in _REQUESTS.items():
            result = await controller.handle_command(request("exec-c"))
            assert result.success is False, signal
            assert result.new_state == "cancelled"
        assert await signals.get_signal("exec-c") is None

    async def test_a_running_execution_is_cancelled(self) -> None:
        """The control: the controller can say yes, so the refusals are about state."""
        executions = _executions()
        signals = InMemorySignalQueueAdapter()
        await _record(executions, "exec-r", ExecutionStatus.RUNNING)

        result = await ExecutionController(executions, signals).handle_command(
            CancelExecution(execution_id="exec-r")
        )

        assert result.success is True
        assert result.message == "Cancel signal queued"
        queued = await signals.get_signal("exec-r")
        assert queued is not None
        assert queued.signal_type == ControlSignalType.CANCEL

    @pytest.mark.parametrize("status", list(_TO_STATUS))
    async def test_inject_is_refused_exactly_when_terminal(self, status: ExecutionStatus) -> None:
        executions = _executions()
        signals = InMemorySignalQueueAdapter()
        await _record(executions, "exec-i", status)

        result = await ExecutionController(executions, signals).handle_command(
            InjectContext(execution_id="exec-i", message="m")
        )

        live = status is ExecutionStatus.RUNNING
        assert result.success is live
        if not live:
            assert "terminal" in (result.error or "").lower()

    async def test_an_execution_with_no_stream_is_refused(self) -> None:
        """No stream is not a pending execution. The old controller read a
        missing row as PENDING, from which cancel and inject were admitted."""
        signals = InMemorySignalQueueAdapter()
        controller = ExecutionController(_executions(), signals)

        for signal, request in _REQUESTS.items():
            result = await controller.handle_command(request("exec-nope"))
            assert result.success is False, signal
            assert "not found" in (result.error or "")
        assert await signals.get_signal("exec-nope") is None
        assert await controller.get_state("exec-nope") is None

    async def test_an_unreachable_event_store_is_refused(self) -> None:
        """Fail closed: a request the controller cannot check is not admitted."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        client = GrpcEventStoreClient(address=f"127.0.0.1:{port}")
        await client.connect()
        signals = InMemorySignalQueueAdapter()
        try:
            result = await ExecutionController(_executions(client), signals).handle_command(
                CancelExecution(execution_id="exec-1")
            )
        finally:
            await client.disconnect()

        assert result.success is False
        assert await signals.get_signal("exec-1") is None


@pytest.mark.unit
class TestExecutionController:
    """What an admitted request queues, and what the executor reads back."""

    async def test_cancel_carries_its_reason(self) -> None:
        executions = _executions()
        signals = InMemorySignalQueueAdapter()
        await _record(executions, "exec-1", ExecutionStatus.RUNNING)

        result = await ExecutionController(executions, signals).handle_command(
            CancelExecution(execution_id="exec-1", reason="Timed out")
        )

        assert result.success
        assert result.message == "Cancel signal queued"
        signal = await signals.dequeue("exec-1")
        assert signal is not None
        assert signal.signal_type == ControlSignalType.CANCEL
        assert signal.reason == "Timed out"

    async def test_inject_carries_its_message(self) -> None:
        executions = _executions()
        signals = InMemorySignalQueueAdapter()
        await _record(executions, "exec-1", ExecutionStatus.RUNNING)

        result = await ExecutionController(executions, signals).handle_command(
            InjectContext(execution_id="exec-1", message="New instructions", role="user")
        )

        assert result.success
        assert result.message == "Context injection queued"
        signal = await signals.dequeue("exec-1")
        assert signal is not None
        assert signal.signal_type == ControlSignalType.INJECT
        assert signal.inject_message == "New instructions"

    async def test_get_state_reads_the_stream(self) -> None:
        executions = _executions()
        await _record(executions, "exec-1", ExecutionStatus.CANCELLED)
        controller = ExecutionController(executions, InMemorySignalQueueAdapter())

        assert await controller.get_state("exec-1") is ExecutionStatus.CANCELLED

    async def test_check_signal_consumes_the_signal(self) -> None:
        executions = _executions()
        await _record(executions, "exec-1", ExecutionStatus.RUNNING)
        controller = ExecutionController(executions, InMemorySignalQueueAdapter())

        assert await controller.check_signal("exec-1") is None
        await controller.handle_command(CancelExecution(execution_id="exec-1"))

        signal = await controller.check_signal("exec-1")
        assert signal is not None
        assert signal.signal_type == ControlSignalType.CANCEL
        assert await controller.check_signal("exec-1") is None


class _FakeTimingOutRedis:
    """Minimal async Redis double whose claim script always raises a timeout.

    Mirrors what a transient `Timeout reading from redis:6379` looks like to
    the adapter, without needing a real Redis server.
    """

    def register_script(self, script: str) -> Callable[..., Awaitable[str | None]]:
        async def run(**_kwargs: object) -> str | None:
            import redis.exceptions

            raise redis.exceptions.TimeoutError("Timeout reading from redis:6379")

        return run


@pytest.mark.unit
class TestRedisSignalQueueFailOpen:
    """#1078: a transient Redis timeout on the signal queue must not fail a phase.

    Exercises the fix through ExecutionController.check_signal() - the actual
    port boundary CancelSignalPoller depends on - rather than calling
    RedisSignalQueueAdapter.dequeue() directly, so the test also catches a
    regression where the fail-open handling is dropped somewhere between the
    adapter and the controller that wraps it.
    """

    @pytest.mark.asyncio
    async def test_check_signal_returns_none_on_redis_timeout(self) -> None:
        signal_adapter = RedisSignalQueueAdapter(_FakeTimingOutRedis())  # type: ignore[arg-type]
        controller = ExecutionController(_executions(), signal_adapter)

        signal = await controller.check_signal("test-exec-timeout")

        assert signal is None


class TestInMemoryAdapters:
    """Tests for in-memory adapter implementations."""

    @pytest.mark.asyncio
    async def test_signal_adapter_fifo_order(self) -> None:
        """Signal adapter maintains FIFO order."""
        from syn_adapters.control.commands import ControlSignal

        adapter = InMemorySignalQueueAdapter()
        execution_id = "exec-1"

        signal1 = ControlSignal(ControlSignalType.CANCEL, execution_id)
        signal2 = ControlSignal(ControlSignalType.INJECT, execution_id)

        await adapter.enqueue(execution_id, signal1)
        await adapter.enqueue(execution_id, signal2)

        result1 = await adapter.dequeue(execution_id)
        result2 = await adapter.dequeue(execution_id)
        result3 = await adapter.dequeue(execution_id)

        assert result1 is not None
        assert result1.signal_type == ControlSignalType.CANCEL
        assert result2 is not None
        assert result2.signal_type == ControlSignalType.INJECT
        assert result3 is None
