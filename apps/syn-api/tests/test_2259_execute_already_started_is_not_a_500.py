"""`POST /execute` answers 200 for a run another starter opened first (#2259).

With the run queue ON the route records the request durably (#1557) and then
starts it inline (#1310 1.3). The request ProcessManager reads the same record
and can open the execution's stream first. The inline start then loses on
NoStream: one execution exists and is running, and the caller must hear that,
not a 500 that tells it to dispatch - and pay for - a second run.

These go through the real `execute()`, so the typed `DuplicateExecutionError`
the handler raises is what the route sees, not an `Err` built by the test. The
race itself runs in #1557's world: the real request ProcessManager, dispatcher,
`ExecuteWorkflowHandler` and processor over one event store.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar
from unittest.mock import MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from test_1557_one_execution_budget import (  # pyright: ignore[reportMissingImports]
    WORKFLOW_ID,
    _World,  # pyright: ignore[reportPrivateUsage]
)

from syn_adapters.execution_runs.memory import InMemoryExecutionRunQueue
from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_api import _wiring
from syn_api.routes.executions import commands, keyed_start
from syn_domain.contexts._shared import AdmissionGate
from syn_domain.contexts.orchestration import (
    DuplicateExecutionError,
    TagSet,
    WorkflowTemplateAggregate,
)
from syn_shared.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syn_domain.contexts._shared.maintenance import AdmissionTicket
    from syn_domain.contexts.orchestration import ExecuteWorkflowCommand

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


@pytest.fixture
def run_queue_flag(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SYN_EXECUTION_RUN_QUEUE_ENABLED", "true")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    monkeypatch.delenv("SYN_EXECUTION_RUN_QUEUE_ENABLED")
    get_settings.cache_clear()  # type: ignore[attr-defined]


class _Request:
    """Enough of ExecuteWorkflowRequest for the endpoint's signature."""

    inputs: ClassVar[dict[str, str]] = {}
    repos: ClassVar[list[str]] = ["https://github.com/syntropic137/syntropic137"]
    task: str | None = None
    idempotency_key: str | None = None
    tags = TagSet()
    eval_id: None = None
    no_eval = False
    provider = "claude"


class _WorkflowRepo:
    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate:
        del aggregate_id
        return WorkflowTemplateAggregate()


class _NoDetail:
    async def get_by_id(self, workflow_id: str) -> None:
        del workflow_id


async def _nothing_to_connect() -> None:
    return None


def _wire_handler_raising(
    monkeypatch: pytest.MonkeyPatch, raises: type[Exception]
) -> tuple[list[str], AdmissionGate]:
    """Wire the route and the real `execute()` around a handler whose start
    raises ``raises(execution_id)``. Returns the ids it was asked to start."""
    import syn_api._wiring_admission as wiring

    started: list[str] = []

    class _Handler:
        async def handle(self, cmd: ExecuteWorkflowCommand, *, admitted: object = None) -> None:
            del admitted
            assert cmd.execution_id is not None
            started.append(cmd.execution_id)
            raise raises(cmd.execution_id)

    async def get_handler() -> _Handler:
        return _Handler()

    gate = AdmissionGate(InMemoryMaintenanceAdapter(), drain_timeout=0.5)
    monkeypatch.setattr(wiring, "_admission_gate_singleton", gate, raising=False)
    monkeypatch.setattr(commands, "ensure_connected", _nothing_to_connect)
    monkeypatch.setattr(commands, "get_workflow_repo", _WorkflowRepo)
    monkeypatch.setattr(
        commands, "get_projection_mgr", lambda: MagicMock(workflow_detail=_NoDetail())
    )
    monkeypatch.setattr(_wiring, "get_execute_workflow_handler", get_handler)
    return started, gate


@pytest.mark.usefixtures("run_queue_flag")
async def test_a_start_the_request_processmanager_won_answers_200_with_its_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, gate = _wire_handler_raising(monkeypatch, DuplicateExecutionError)
    tasks = BackgroundTasks()

    response = await commands.execute_workflow_endpoint(
        "wf-1",
        _Request(),  # type: ignore[arg-type]
        tasks,
    )

    assert response.replayed is True
    assert started == [response.execution_id], "one start attempt, for this id"
    assert tasks.tasks == [], "and no second start queued behind the 200"
    # #1387 unchanged: the route's ticket settled, so a pause does not wait on it.
    await gate.set_mode(active=True, reason="deploy", actor="test")


class _StoreDown(Exception):
    def __init__(self, execution_id: str) -> None:
        super().__init__(f"event store unreachable while starting {execution_id}")


@pytest.mark.usefixtures("run_queue_flag")
async def test_a_start_that_genuinely_failed_is_still_a_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, _gate = _wire_handler_raising(monkeypatch, _StoreDown)

    with pytest.raises(HTTPException) as refused:
        await commands.execute_workflow_endpoint(
            "wf-1",
            _Request(),  # type: ignore[arg-type]
            BackgroundTasks(),
        )

    assert refused.value.status_code == 500
    assert "event store unreachable" in str(refused.value.detail)
    assert len(started) == 1


@pytest.mark.usefixtures("run_queue_flag")
@pytest.mark.parametrize("idempotency_key", [None, "race-2259"])
async def test_when_the_request_processmanager_starts_it_first_there_is_one_execution(
    monkeypatch: pytest.MonkeyPatch, idempotency_key: str | None
) -> None:
    """The race of #2259, with the real winner: the request is durable, the
    request ProcessManager starts it from that record, and only then does the
    route's inline start run."""
    world = _World(monkeypatch)
    world.handler._processor._run_queue = InMemoryExecutionRunQueue()  # pyright: ignore[reportPrivateUsage]
    world.dispatcher._admits_to_run_queue = True  # pyright: ignore[reportPrivateUsage]
    record = keyed_start.record_execution_request
    won: list[str] = []

    async def processmanager_wins(
        command: ExecuteWorkflowCommand, admitted: AdmissionTicket
    ) -> None:
        await record(command, admitted)
        assert await world.coordinate() == (0, 1), "the ProcessManager offers the request"
        assert command.execution_id is not None
        assert command.execution_id in world.executions.streams
        won.append(command.execution_id)

    monkeypatch.setattr(keyed_start, "record_execution_request", processmanager_wins)
    tasks = BackgroundTasks()

    response = await commands.execute_workflow_endpoint(
        WORKFLOW_ID,
        commands.ExecuteWorkflowRequest(idempotency_key=idempotency_key),
        tasks,
    )

    assert response.replayed is True
    assert won == [response.execution_id], "the 200 names the run that is running"
    assert list(world.executions.streams) == [response.execution_id], "one execution"
    starts = [
        e.metadata.aggregate_id
        for e in world.log.envelopes
        if e.metadata.event_type == "WorkflowExecutionStarted"
    ]
    assert starts == [response.execution_id], "started once"
    assert tasks.tasks == [], "no second start queued behind the 200"
    assert await world.coordinate() == (0, 0), "and nothing left to offer"
    # #1387 unchanged: both tickets settled, so a pause does not wait on them.
    await world.gate.set_mode(active=True, reason="deploy", actor="test")
