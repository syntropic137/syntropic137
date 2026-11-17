"""#1530: inject is refused, and an inject attempt cannot erase a pending cancel.

THE DEFECT. `POST /executions/{id}/inject` answered 200 "Context injection
queued", but no execution path reads an injected message: the cancel poller
dequeues it and drops it. Worse, production keeps one signal per execution, so
the queued INJECT replaced a pending CANCEL and the cancel was lost.

WHAT IS REAL HERE. The app and its routes, the controller, the execution
aggregate and the event-store repository. The signal queue is the in-memory
one, which keeps every signal in order, so anything an inject queued is seen.
The Redis slot's own rule (a cancel is never overwritten) is pinned beside the
adapter, in `packages/syn-adapters/tests/test_redis_retry_hazard.py`.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

import syn_api._wiring as wiring
from syn_adapters.control import ControlSignalType, ExecutionController
from syn_adapters.control.adapters.memory import InMemorySignalQueueAdapter
from syn_api.routes.executions import control
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    StartExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

EXECUTION = "exec-1530a0b1c2d3"
REFUSAL = "Injecting a message into a running agent is not supported"


@pytest.fixture(autouse=True)
def _reset_storage() -> Iterator[None]:
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    yield
    reset_storage()
    reset_projection_manager()


@pytest.fixture
def signals(monkeypatch: pytest.MonkeyPatch) -> InMemorySignalQueueAdapter:
    queue = InMemorySignalQueueAdapter()
    controller = ExecutionController(wiring.get_workflow_execution_repository(), queue)
    monkeypatch.setattr(control, "get_controller", lambda: controller)
    return queue


@pytest.fixture
async def client(signals: InMemorySignalQueueAdapter) -> AsyncIterator[AsyncClient]:
    del signals
    from syn_api.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


async def _running() -> None:
    """A running execution: the one state in which inject used to be admitted."""
    await wiring.ensure_connected()
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=EXECUTION,
            workflow_id="wf-1530",
            workflow_name="Inject Target",
            total_phases=1,
            inputs={"task": "t"},
            phase_definitions=[PhaseDefinition(phase_id="work", name="Work", order=1)],
        )
    )
    await wiring.get_workflow_execution_repository().save(aggregate)
    assert aggregate.accepts_control(ControlSignalType.CANCEL), "not running"


async def test_inject_is_refused_and_queues_nothing(
    client: AsyncClient, signals: InMemorySignalQueueAdapter
) -> None:
    await _running()

    response = await client.post(
        f"/executions/{EXECUTION}/inject", json={"message": "also fix the docs"}
    )

    assert response.status_code == 501, response.text
    assert response.json()["detail"].startswith(REFUSAL)
    assert await signals.dequeue(EXECUTION) is None, "an inject was queued"


async def test_a_queued_cancel_survives_an_inject_attempt(
    client: AsyncClient, signals: InMemorySignalQueueAdapter
) -> None:
    await _running()
    cancelled = await client.post(f"/executions/{EXECUTION}/cancel", json={"reason": "wrong task"})
    assert cancelled.status_code == 200, cancelled.text

    injected = await client.post(f"/executions/{EXECUTION}/inject", json={"message": "never mind"})

    assert injected.status_code == 501, injected.text
    pending = await signals.dequeue(EXECUTION)
    assert pending is not None, "the cancel was lost"
    assert pending.signal_type is ControlSignalType.CANCEL
    assert pending.reason == "wrong task"
    assert await signals.dequeue(EXECUTION) is None, "the inject was queued behind the cancel"


def test_the_spec_declares_the_refusal() -> None:
    """Clients are generated from the spec, so the 501 must be in it, typed."""
    from syn_api.main import create_app

    spec = create_app().openapi()
    responses = spec["paths"]["/executions/{execution_id}/inject"]["post"]["responses"]
    schema = responses["501"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/ControlNotSupportedResponse"}
