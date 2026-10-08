"""#1555: cancel and resume work while the execution read model is rebuilt.

THE INCIDENT. After an API OOM orphaned six executions, `syn execution resume`
answered "Execution not found" for every one: `workflow_execution_details` was
replaying after a version bump, and the command resolved its id through it.
Resume is the recovery path for exactly that incident.

WHAT IS REAL HERE. The app and its routes, the id resolver, the execution
aggregates and the event-store repository, the controller and `resume()`. The
doubles are the signal queue (Redis in production), the artifact query and the
subscription service's lag measurement, which is produced by the real
`measure_read_model_lag` and only handed over by a stub.

"CLEARED" is what a version bump does to the read model: every row gone. Each
test asserts the row is absent before it acts, so none passes by finding it.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

import syn_api._wiring as wiring
from syn_adapters.control import ExecutionController
from syn_adapters.control.adapters.memory import InMemorySignalQueueAdapter
from syn_adapters.subscriptions.read_model_lag import (
    CheckpointState,
    ReadModelLag,
    measure_read_model_lag,
)
from syn_api.routes.executions import control
from syn_api.services import lifecycle
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    FailExecutionCommand,
    StartExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    FailureClassification,
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Mapping, Sequence

    from syn_domain.contexts.artifacts import PhaseOutputFile

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

EXECUTION = "exec-1555a0b1c2d3"
PREFIX = EXECUTION[:10]
READ_MODEL = "workflow_execution_details"
PHASES = ("research", "plan")
HEAD = 5000
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset_storage() -> Iterator[None]:
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    if hasattr(store, "_state"):
        store._state.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    yield
    reset_storage()
    reset_projection_manager()


class _NoArtifacts:
    """Nothing to inherit: the parents here failed before completing a phase."""

    async def get_files_for_artifacts(
        self, execution_id: str, phase_artifact_ids: Mapping[str, Sequence[str]]
    ) -> dict[str, list[PhaseOutputFile]]:
        del execution_id, phase_artifact_ids
        return {}


class _SubscriptionServiceStub:
    """The started subscription service, as far as the resolver asks it."""

    def __init__(self, lag: ReadModelLag) -> None:
        self._lag = lag

    async def describe_read_model_lag(self) -> ReadModelLag:
        return self._lag


@pytest.fixture
def signals(monkeypatch: pytest.MonkeyPatch) -> InMemorySignalQueueAdapter:
    queue = InMemorySignalQueueAdapter()
    controller = ExecutionController(wiring.get_workflow_execution_repository(), queue)
    monkeypatch.setattr(control, "get_controller", lambda: controller)
    monkeypatch.setattr(wiring, "get_artifact_query", _NoArtifacts)
    return queue


@pytest.fixture
async def client(signals: InMemorySignalQueueAdapter) -> AsyncIterator[AsyncClient]:
    del signals
    from syn_api.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


@pytest.fixture
def rebuilding(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`workflow_execution_details` replaying from 0, as a version bump leaves it."""
    _install(monkeypatch, _lag(behind=READ_MODEL))
    yield


def _lag(*, behind: str) -> ReadModelLag:
    peers = ("workflow_executions", "session_summaries")
    return measure_read_model_lag(
        head_position=HEAD,
        checkpoints={
            name: CheckpointState(position=0 if name == behind else HEAD, updated_at=NOW)
            for name in (READ_MODEL, *peers)
        },
        projection_names=[READ_MODEL, *peers],
        replaying=True,
        now=NOW,
    )


def _install(monkeypatch: pytest.MonkeyPatch, lag: ReadModelLag) -> None:
    stub = _SubscriptionServiceStub(lag)
    monkeypatch.setattr(lifecycle._state, "subscription_service", stub)


def _started() -> WorkflowExecutionAggregate:
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=EXECUTION,
            workflow_id="wf-1555",
            workflow_name="Rebuild Survivor",
            total_phases=len(PHASES),
            inputs={"task": "t"},
            phase_definitions=[
                PhaseDefinition(phase_id=p, name=p.title(), order=i + 1)
                for i, p in enumerate(PHASES)
            ],
            pinned_phases=[
                ExecutablePhase(
                    phase_id=p,
                    name=p.title(),
                    order=i + 1,
                    agent_config=AgentConfiguration(),
                    prompt_template=f"{p} as pinned",
                    output_artifact_types=(),
                    timeout_seconds=1800,
                )
                for i, p in enumerate(PHASES)
            ],
        )
    )
    return aggregate


def _failed() -> WorkflowExecutionAggregate:
    aggregate = _started()
    aggregate.fail_execution(
        FailExecutionCommand(
            execution_id=EXECUTION,
            error="the API was OOM-killed",
            error_type="AgentError",
            failed_phase_id="research",
            completed_phases=0,
            total_phases=len(PHASES),
            classification=FailureClassification.UNCLASSIFIED,
        )
    )
    return aggregate


async def _stored_with_read_model_cleared(aggregate: WorkflowExecutionAggregate) -> None:
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    await wiring.get_workflow_execution_repository().save(aggregate)
    store = get_projection_mgr().store
    await store.delete_all(READ_MODEL)
    assert await store.get(READ_MODEL, EXECUTION) is None, "the read model was not cleared"


class TestAFullIdNeedsNoReadModel:
    async def test_cancel_reaches_the_running_execution(
        self, client: AsyncClient, signals: InMemorySignalQueueAdapter, rebuilding: None
    ) -> None:
        await _stored_with_read_model_cleared(_started())

        response = await client.post(f"/executions/{EXECUTION}/cancel", json={"reason": "swap"})

        assert response.status_code == 200, response.text
        assert response.json()["execution_id"] == EXECUTION
        signal = await signals.dequeue(EXECUTION)
        assert signal is not None
        assert signal.reason == "swap"

    async def test_resume_is_admitted_and_recorded_on_the_parent(
        self, client: AsyncClient, rebuilding: None
    ) -> None:
        await _stored_with_read_model_cleared(_failed())

        response = await client.post(f"/executions/{EXECUTION}/resume", json={})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["parent_execution_id"] == EXECUTION
        assert body["resume_phase_id"] == "research"
        parent = await wiring.get_workflow_execution_repository().get_by_id(EXECUTION)
        assert parent is not None
        assert parent.resume_execution_id == body["execution_id"]

    async def test_it_works_with_no_subscription_at_all(self, client: AsyncClient) -> None:
        """No rebuild signal is needed for a full id: the store alone answers."""
        await _stored_with_read_model_cleared(_failed())

        response = await client.post(f"/executions/{EXECUTION}/resume", json={})

        assert response.status_code == 200, response.text


class TestAPrefixDuringTheRebuild:
    @pytest.mark.parametrize("command", ["cancel", "resume"])
    async def test_is_409_naming_the_rebuild(
        self, client: AsyncClient, rebuilding: None, command: str
    ) -> None:
        await _stored_with_read_model_cleared(_failed())

        response = await client.post(f"/executions/{PREFIX}/{command}", json={})

        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert "rebuilding" in detail
        assert PREFIX in detail
        assert "full execution id" in detail

    async def test_cancel_still_offers_it_to_the_queued_start_withdrawal(
        self, client: AsyncClient, rebuilding: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A queued start has no stream, so a rebuild hides it like any other (#1650)."""
        asked: list[str] = []

        async def _withdraw(execution_id: str, reason: str | None) -> control.ControlResponse:
            del reason
            asked.append(execution_id)
            return control.ControlResponse(
                success=True, execution_id=EXECUTION, state="cancelled", message="withdrawn"
            )

        monkeypatch.setattr(control, "_withdraw_queued", _withdraw)

        response = await client.post(f"/executions/{PREFIX}/cancel", json={})

        assert response.status_code == 200, response.text
        assert asked == [PREFIX]

    async def test_a_rebuild_of_another_read_model_leaves_a_miss_a_404(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only the read model that expands the prefix can make a miss inconclusive."""
        _install(monkeypatch, _lag(behind="session_summaries"))
        await _stored_with_read_model_cleared(_failed())

        response = await client.post(f"/executions/{PREFIX}/resume", json={})

        assert response.status_code == 404, response.text


class TestAnUnknownFullIdIsStillNotFound:
    async def test_resume_of_an_id_with_no_stream_is_404(self, client: AsyncClient) -> None:
        response = await client.post("/executions/exec-000000000000/resume", json={})

        assert response.status_code == 404, response.text


class TestStateDuringAStoreOutage:
    async def test_is_503_not_500(
        self, signals: InMemorySignalQueueAdapter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The store probe now runs first; its outage keeps the 503 get_state() gave."""
        from event_sourcing import EventStoreError

        from syn_adapters.projections.sync import sync_published_events_to_projections
        from syn_adapters.storage.event_store_client import get_event_store_client
        from syn_api.main import create_app

        del signals
        await wiring.ensure_connected()
        await wiring.get_workflow_execution_repository().save(_started())
        await sync_published_events_to_projections()
        assert await wiring.get_projection_mgr().store.get(READ_MODEL, EXECUTION) is not None

        async def _outage(*args: object, **kwargs: object) -> bool:
            del args, kwargs
            raise EventStoreError("simulated event store outage")

        event_store = get_event_store_client()
        monkeypatch.setattr(event_store, "stream_exists", _outage)
        monkeypatch.setattr(event_store, "read_events", _outage)
        transport = ASGITransport(app=create_app(), raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://t") as http:
            response = await http.get(f"/executions/{EXECUTION}/state")

        assert response.status_code == 503, response.text
        assert "event store could not be read" in response.json()["detail"]

    async def test_a_full_id_still_answers_during_the_rebuild(
        self, client: AsyncClient, rebuilding: None
    ) -> None:
        await _stored_with_read_model_cleared(_started())

        response = await client.get(f"/executions/{EXECUTION}/state")

        assert response.status_code == 200, response.text
        assert response.json() == {"execution_id": EXECUTION, "state": "running"}
