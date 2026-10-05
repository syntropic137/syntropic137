"""#967: eval membership and a workflow's default eval are edited over HTTP.

Every test goes through the real app (`create_app()`), the real route, the
real handler, the real aggregates and the real event-store repositories; only
the store is in memory. What is asserted is what reached the STREAM, read back
from the event store client, not only what the route said it did (#955).

The launch path is pinned to the request boundary: an eval that cannot take
runs is refused with a status BEFORE anything is queued, and the choice the
request made reaches `execute()`. The handler test
(`execute_workflow/test_967_eval_membership.py`) takes it from there.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_domain.contexts._shared import AdmissionGate
from syn_domain.contexts.orchestration import TagSet, WorkflowExecutionAggregate
from syn_domain.contexts.orchestration._shared.eval_choice import EvalSelection, LaunchEval
from syn_domain.contexts.orchestration.domain.aggregate_eval import EvalId, Goal
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    StartExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.events import (
    ExecutionAttachedToEvalEvent,
    ExecutionDetachedFromEvalEvent,
)
from syn_domain.contexts.orchestration.slices.archive_eval import ArchiveEvalHandler
from syn_domain.contexts.orchestration.slices.create_eval import CreateEvalHandler
from syn_domain.testing.fake_revision_resolver import FakeRevisionResolver

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from syn_domain.contexts._shared import AdmissionTicket

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

EXECUTION_ID = "exec-eval-967-0001"
EXEC_PATH = f"/executions/{EXECUTION_ID}/eval"
EXEC_STREAM = f"WorkflowExecution-{EXECUTION_ID}"


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


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from syn_api.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


async def _create_eval(eval_id: str, *, archived: bool = False) -> None:
    from syn_api._wiring import ensure_connected, get_eval_repo

    await ensure_connected()
    created = await CreateEvalHandler(get_eval_repo(), FakeRevisionResolver()).handle(
        eval_id=EvalId(eval_id), name=eval_id, goal=Goal("Keep tests green")
    )
    assert created.success
    if archived:
        result = await ArchiveEvalHandler(get_eval_repo()).handle(eval_id=EvalId(eval_id))
        assert result is not None and result.success


async def _launch_execution(eval_id: str | None = None) -> None:
    """An execution launched into ``eval_id`` (or none), saved like a real one."""
    from syn_api._wiring import ensure_connected, get_workflow_execution_repository

    await ensure_connected()
    selection = EvalSelection.EXPLICIT if eval_id else EvalSelection.NONE
    aggregate = WorkflowExecutionAggregate()
    aggregate._handle_command(  # pyright: ignore[reportPrivateUsage]
        StartExecutionCommand(
            execution_id=EXECUTION_ID,
            workflow_id="wf-eval-967",
            workflow_name="Evaluated",
            total_phases=1,
            inputs={},
            tags=TagSet(),
            launch_eval=LaunchEval(eval_id, selection),
        )
    )
    await get_workflow_execution_repository().save_new(aggregate)


async def _create_workflow() -> str:
    from syn_api.routes.workflows import create_workflow
    from syn_api.types import Ok

    result = await create_workflow(
        name="Eval workflow", workflow_type="research", requires_repos=False
    )
    assert isinstance(result, Ok)
    return result.value.workflow_id


@dataclass(frozen=True)
class _Edit:
    """One membership edit as persisted, without its timestamp."""

    type: str
    eval_id: str


async def _membership_events(stream: str) -> list[_Edit]:
    """The membership edits persisted on a stream, in order."""
    from syn_adapters.storage.event_store_client import get_event_store_client

    envelopes = await get_event_store_client().read_events(stream)
    return [
        _Edit(e.event.event_type, e.event.eval_id)
        for e in envelopes
        if isinstance(e.event, ExecutionAttachedToEvalEvent | ExecutionDetachedFromEvalEvent)
    ]


class TestAttachAndDetach:
    async def test_attach_persists_one_event_and_a_duplicate_records_nothing(
        self, client: AsyncClient
    ) -> None:
        await _create_eval("eval-a")
        await _launch_execution()

        first = await client.post(EXEC_PATH, json={"eval_id": "eval-a"})
        again = await client.post(EXEC_PATH, json={"eval_id": "eval-a"})

        assert first.status_code == 200, first.text
        assert again.status_code == 200, again.text
        assert first.json() == {
            "execution_id": EXECUTION_ID,
            "eval_id": "eval-a",
            "association_kind": "attached",
            "launched_eval_id": None,
        }
        assert again.json() == first.json()
        assert await _membership_events(EXEC_STREAM) == [_Edit("ExecutionAttachedToEval", "eval-a")]

    async def test_a_conflicting_attach_is_409_until_detached(self, client: AsyncClient) -> None:
        await _create_eval("eval-a")
        await _create_eval("eval-b")
        await _launch_execution("eval-a")

        refused = await client.post(EXEC_PATH, json={"eval_id": "eval-b"})
        detached = await client.delete(EXEC_PATH, params={"eval_id": "eval-a"})
        attached = await client.post(EXEC_PATH, json={"eval_id": "eval-b"})

        assert refused.status_code == 409, refused.text
        assert "detach it before" in refused.json()["detail"]
        assert detached.status_code == 200, detached.text
        assert detached.json() == {
            "execution_id": EXECUTION_ID,
            "eval_id": None,
            "association_kind": None,
            "launched_eval_id": "eval-a",
        }
        assert attached.json()["association_kind"] == "attached"
        assert attached.json()["launched_eval_id"] == "eval-a"
        assert await _membership_events(EXEC_STREAM) == [
            _Edit("ExecutionDetachedFromEval", "eval-a"),
            _Edit("ExecutionAttachedToEval", "eval-b"),
        ]

    @pytest.mark.parametrize(
        ("archived", "status"), [(True, 409), (None, 404)], ids=["archived", "missing"]
    )
    async def test_an_eval_that_cannot_take_runs_is_refused(
        self, client: AsyncClient, archived: bool | None, status: int
    ) -> None:
        if archived is not None:
            await _create_eval("eval-a", archived=archived)
        await _launch_execution()

        response = await client.post(EXEC_PATH, json={"eval_id": "eval-a"})

        assert response.status_code == status, response.text
        assert await _membership_events(EXEC_STREAM) == []

    async def test_detach_from_another_eval_is_409(self, client: AsyncClient) -> None:
        await _create_eval("eval-a")
        await _launch_execution("eval-a")

        response = await client.delete(EXEC_PATH, params={"eval_id": "eval-b"})

        assert response.status_code == 409, response.text
        assert await _membership_events(EXEC_STREAM) == []

    async def test_an_unknown_execution_is_404(self, client: AsyncClient) -> None:
        await _create_eval("eval-a")

        response = await client.post("/executions/exec-nope/eval", json={"eval_id": "eval-a"})

        assert response.status_code == 404, response.text

    async def test_an_invalid_eval_id_is_422(self, client: AsyncClient) -> None:
        await _launch_execution()

        attach = await client.post(EXEC_PATH, json={"eval_id": "has spaces"})
        detach = await client.delete(EXEC_PATH, params={"eval_id": "has spaces"})

        assert attach.status_code == 422
        assert detach.status_code == 422


class TestWorkflowDefaultEval:
    async def test_set_and_clear_persist_and_reach_the_detail(self, client: AsyncClient) -> None:
        await _create_eval("eval-a")
        workflow_id = await _create_workflow()
        path = f"/workflows/{workflow_id}/default-eval"

        set_it = await client.put(path, json={"eval_id": "eval-a"})
        detail = await client.get(f"/workflows/{workflow_id}")
        cleared = await client.put(path, json={"eval_id": None})

        assert set_it.status_code == 200, set_it.text
        assert set_it.json() == {"workflow_id": workflow_id, "default_eval_id": "eval-a"}
        assert detail.json()["default_eval_id"] == "eval-a"
        assert cleared.json() == {"workflow_id": workflow_id, "default_eval_id": None}

        from syn_adapters.storage.event_store_client import get_event_store_client

        envelopes = await get_event_store_client().read_events(f"WorkflowTemplate-{workflow_id}")
        assert [
            e.event.model_dump()["eval_id"]
            for e in envelopes
            if e.event.event_type == "WorkflowDefaultEvalSet"
        ] == ["eval-a", None]

    async def test_an_archived_default_is_409(self, client: AsyncClient) -> None:
        await _create_eval("eval-a", archived=True)
        workflow_id = await _create_workflow()

        response = await client.put(
            f"/workflows/{workflow_id}/default-eval", json={"eval_id": "eval-a"}
        )

        assert response.status_code == 409, response.text

    async def test_an_unknown_workflow_is_404(self, client: AsyncClient) -> None:
        response = await client.put("/workflows/wf-nope/default-eval", json={"eval_id": None})

        assert response.status_code == 404, response.text


class _CapturingExecute:
    """Stands in for `execute()`, keeping only the resolved eval the route handed it."""

    def __init__(self) -> None:
        self.choices: list[LaunchEval | None] = []

    async def __call__(
        self,
        *,
        admitted: AdmissionTicket | None = None,
        launch_eval: LaunchEval | None = None,
        **_: object,
    ) -> None:
        self.choices.append(launch_eval)
        if admitted is not None:
            admitted.mark_visible()


@pytest.fixture
def execution(monkeypatch: pytest.MonkeyPatch) -> _CapturingExecute:
    import syn_api._wiring_admission as wiring
    from syn_api.routes.executions import commands

    captured = _CapturingExecute()
    monkeypatch.setattr(
        wiring,
        "_admission_gate_singleton",
        AdmissionGate(InMemoryMaintenanceAdapter()),
        raising=False,
    )
    monkeypatch.setattr(commands, "execute", captured)
    return captured


@dataclass(frozen=True)
class _Launch:
    """The eval half of an execute request; a field left unset is not sent."""

    eval_id: str | None = None
    no_eval: bool | None = None

    def body(self) -> dict[str, str | bool]:
        sent = {"eval_id": self.eval_id, "no_eval": self.no_eval}
        return {name: value for name, value in sent.items() if value is not None}


class TestTheLaunchChoosesAnEval:
    async def _run(self, client: AsyncClient, workflow_id: str, launch: _Launch) -> int:
        response = await client.post(f"/workflows/{workflow_id}/execute", json=launch.body())
        return response.status_code

    async def test_an_explicit_eval_reaches_execute(
        self, client: AsyncClient, execution: _CapturingExecute
    ) -> None:
        await _create_eval("eval-a")
        workflow_id = await _create_workflow()

        assert await self._run(client, workflow_id, _Launch(eval_id="eval-a")) == 200

        assert execution.choices == [LaunchEval("eval-a", EvalSelection.EXPLICIT)]

    async def test_no_eval_reaches_execute_as_an_ordinary_run(
        self, client: AsyncClient, execution: _CapturingExecute
    ) -> None:
        await _create_eval("eval-a")
        workflow_id = await _create_workflow()
        await client.put(f"/workflows/{workflow_id}/default-eval", json={"eval_id": "eval-a"})

        assert await self._run(client, workflow_id, _Launch(no_eval=True)) == 200

        assert execution.choices == [LaunchEval(None, EvalSelection.ORDINARY)]

    @pytest.mark.parametrize(
        ("archived", "status"), [(True, 409), (None, 404)], ids=["archived", "missing"]
    )
    async def test_an_eval_that_cannot_take_runs_is_refused_before_queueing(
        self,
        client: AsyncClient,
        execution: _CapturingExecute,
        archived: bool | None,
        status: int,
    ) -> None:
        if archived is not None:
            await _create_eval("eval-a", archived=archived)
        workflow_id = await _create_workflow()

        assert await self._run(client, workflow_id, _Launch(eval_id="eval-a")) == status

        assert execution.choices == []

    async def test_an_archived_workflow_default_is_refused_before_queueing(
        self, client: AsyncClient, execution: _CapturingExecute
    ) -> None:
        await _create_eval("eval-a")
        workflow_id = await _create_workflow()
        await client.put(f"/workflows/{workflow_id}/default-eval", json={"eval_id": "eval-a"})
        from syn_api._wiring import get_eval_repo

        archived = await ArchiveEvalHandler(get_eval_repo()).handle(eval_id=EvalId("eval-a"))
        assert archived is not None and archived.success

        refused = await self._run(client, workflow_id, _Launch())
        ordinary = await self._run(client, workflow_id, _Launch(no_eval=True))

        assert refused == 409
        assert ordinary == 200
        assert execution.choices == [LaunchEval(None, EvalSelection.ORDINARY)]

    async def test_eval_id_and_no_eval_together_are_422(
        self, client: AsyncClient, execution: _CapturingExecute
    ) -> None:
        workflow_id = await _create_workflow()

        assert await self._run(client, workflow_id, _Launch(eval_id="eval-a", no_eval=True)) == 422

        assert execution.choices == []
