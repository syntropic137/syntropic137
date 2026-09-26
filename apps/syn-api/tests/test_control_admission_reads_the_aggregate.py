"""Control requests are admitted on the aggregate's word, not the read model's.

ADR-014 section 7, fail-open 1. `ExecutionController` used to decide whether to
admit pause/resume/cancel/inject from the execution detail PROJECTION. A
projection lags the stream it derives from, so for the length of that lag an
execution the aggregate had already cancelled still read `running`, and a
request the aggregate would refuse was admitted, reported as success and queued.

The lag here is real, not a hand-set row: the execution is started and synced
through the same path the API uses, then cancelled and saved WITHOUT syncing,
which is exactly the window between `repository.save` and the subscription
catching up. Both sides of that window are asserted before anything is asked.
The requests go through the route service functions and `get_controller()`, so
what is under test is the wiring a caller actually gets.
"""

import os

import pytest

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")

EXECUTION_ID = "exec-adr014-lag"


@pytest.fixture(autouse=True)
def _reset_storage():
    """Reset in-memory storage and projections between tests."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()
    if hasattr(store, "_state"):
        store._state.clear()
    yield
    reset_storage()
    reset_projection_manager()


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch):
    """A fresh controller from `get_controller()`, queueing where we can look."""
    import syn_adapters.control.adapters.redis_adapter as redis_adapter
    import syn_api._wiring as wiring
    from syn_adapters.control.adapters.memory import InMemorySignalQueueAdapter

    signals = InMemorySignalQueueAdapter()
    monkeypatch.setattr(wiring, "_controller_singleton", None)
    monkeypatch.setattr(redis_adapter, "RedisSignalQueueAdapter", lambda _client: signals)
    return signals


async def _start_and_project() -> None:
    """Start an execution and let the read model see it, as the API does."""
    from syn_adapters.storage.repositories import get_workflow_execution_repository
    from syn_api._wiring import ensure_connected, sync_published_events_to_projections
    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        StartExecutionCommand,
        StartPhaseCommand,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        PhaseDefinition,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )

    await ensure_connected()
    agg = WorkflowExecutionAggregate()
    agg.start_execution(
        StartExecutionCommand(
            execution_id=EXECUTION_ID,
            workflow_id="wf-adr014",
            workflow_name="ADR-014",
            total_phases=1,
            inputs={"task": "t"},
            phase_definitions=[PhaseDefinition(phase_id="p1", name="P1", order=1)],
        )
    )
    agg.start_phase(
        StartPhaseCommand(
            execution_id=EXECUTION_ID,
            workflow_id="wf-adr014",
            phase_id="p1",
            phase_name="P1",
            phase_order=1,
        )
    )
    await get_workflow_execution_repository().save_new(agg)
    await sync_published_events_to_projections()


async def _save_without_syncing(step: str) -> None:
    """Move the aggregate on and leave the read model behind: the lag window."""
    from syn_adapters.storage.repositories import get_workflow_execution_repository
    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        CancelExecutionCommand,
        PauseExecutionCommand,
    )

    repo = get_workflow_execution_repository()
    agg = await repo.get_by_id(EXECUTION_ID)
    assert agg is not None
    if step == "cancel":
        agg.cancel_execution(CancelExecutionCommand(execution_id=EXECUTION_ID, phase_id="p1"))
    else:
        agg.pause_execution(PauseExecutionCommand(execution_id=EXECUTION_ID, phase_id="p1"))
    await repo.save(agg)


async def _projected_status() -> str:
    from syn_adapters.projection_stores import get_projection_store

    row = await get_projection_store().get("workflow_execution_details", EXECUTION_ID)
    assert row is not None
    return str(row["status"])


async def _stream_status() -> str:
    from syn_adapters.storage.repositories import get_workflow_execution_repository

    agg = await get_workflow_execution_repository().get_by_id(EXECUTION_ID)
    assert agg is not None
    return agg.status.value


async def test_a_cancelled_execution_the_read_model_still_shows_running_refuses_control(
    queue,
) -> None:
    from syn_api.routes.executions.control import cancel, inject, pause
    from syn_api.types import Ok

    await _start_and_project()
    await _save_without_syncing("cancel")

    # The hazard, present: the two sides disagree, from real lag.
    assert await _projected_status() == "running"
    assert await _stream_status() == "cancelled"

    for request in (
        pause(EXECUTION_ID, reason="r"),
        cancel(EXECUTION_ID, reason="r"),
        inject(EXECUTION_ID, message="m"),
    ):
        result = await request
        assert isinstance(result, Ok)
        assert result.value.success is False
        assert result.value.new_state == "cancelled"

    assert await queue.get_signal(EXECUTION_ID) is None

    # And it was lag, not a read model that could never have caught up.
    from syn_api._wiring import sync_published_events_to_projections

    await sync_published_events_to_projections()
    assert await _projected_status() == "cancelled"


async def test_a_running_execution_is_still_admitted(queue) -> None:
    """The control: the same path says yes when the aggregate would."""
    from syn_adapters.control import ControlSignalType
    from syn_api.routes.executions.control import pause
    from syn_api.types import Ok

    await _start_and_project()
    assert await _projected_status() == "running"
    assert await _stream_status() == "running"

    result = await pause(EXECUTION_ID, reason="r")

    assert isinstance(result, Ok)
    assert result.value.success is True
    signal = await queue.get_signal(EXECUTION_ID)
    assert signal is not None
    assert signal.signal_type == ControlSignalType.PAUSE


async def test_a_paused_execution_the_read_model_shows_running_resumes(queue) -> None:
    """The other direction of the same lag: a request the aggregate accepts."""
    from syn_adapters.control import ControlSignalType
    from syn_api.routes.executions.control import resume
    from syn_api.types import Ok

    await _start_and_project()
    await _save_without_syncing("pause")
    assert await _projected_status() == "running"
    assert await _stream_status() == "paused"

    result = await resume(EXECUTION_ID)

    assert isinstance(result, Ok)
    assert result.value.success is True
    assert result.value.new_state == "paused"
    signal = await queue.get_signal(EXECUTION_ID)
    assert signal is not None
    assert signal.signal_type == ControlSignalType.RESUME


async def test_an_execution_nobody_started_is_refused(queue) -> None:
    """No stream is not a pending execution that may be cancelled."""
    from syn_api._wiring import ensure_connected
    from syn_api.routes.executions.control import cancel, inject
    from syn_api.types import Ok

    await ensure_connected()
    for request in (cancel("exec-never-started"), inject("exec-never-started", message="m")):
        result = await request
        assert isinstance(result, Ok)
        assert result.value.success is False
    assert await queue.get_signal("exec-never-started") is None
