"""#2129: `POST /workflows/{id}/execute` with an `idempotency_key` starts once.

THE GAP. `scripts/eval_suite.py launch --trials` wrote each trial's intent
before its execute call and, when the answer was lost, looked the run up by its
`trial:<batch>/<i>` tag. The server reserved nothing: a lagging list read left
an intent unresolved, and a blind retry started a second run.

WHAT IS REAL HERE. The route function, the request record it writes, the
event store's NoStream guard on that record (the in-memory client enforces it
as the Postgres store does) and the admission gate. Only the workflow lookup
and `execute()` itself are doubles: the test asks whether a start was queued,
not what the start then does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError

import syn_adapters.storage.repositories as repositories
import syn_api._wiring_admission as admission
from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_api.routes.executions import commands, keyed_start
from syn_api.routes.executions.commands import (
    ExecuteWorkflowRequest,
    ExecuteWorkflowResponse,
)
from syn_domain.contexts._shared import AdmissionGate
from syn_domain.contexts.orchestration import (
    TagSet,
    WorkflowTemplateAggregate,
    execution_id_for_key,
    execution_request_id,
)
from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import EvalId
from syn_domain.contexts.orchestration.domain.aggregate_execution_request import (
    ExecutionRequestAggregate,
)

if TYPE_CHECKING:
    from syn_domain.contexts._shared import AdmissionTicket

pytestmark = pytest.mark.unit

WORKFLOW_ID = "wf-2129"
KEY = "trial:b2129/1"
REPO = "https://github.com/syntropic137/syntropic137"


class _WorkflowRepo:
    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate:
        del aggregate_id
        return WorkflowTemplateAggregate()


class _Starts:
    """Stands in for `execute()`: the execution ids it was asked to start."""

    def __init__(self) -> None:
        self.ids: list[str] = []

    async def __call__(
        self,
        *,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str,
        task: str | None,
        repos: list[object],
        admitted: AdmissionTicket | None = None,
        tags: TagSet | None = None,
        launch_eval: object = None,
    ) -> None:
        del workflow_id, inputs, task, repos, tags, launch_eval
        self.ids.append(execution_id)
        if admitted is not None:
            admitted.mark_visible()


class _Requests(RepositoryAdapter[ExecutionRequestAggregate]):
    """The real repository over a memory store, whose first `misses` reads see nothing.

    A miss is the race: a concurrent start with the same key writes the
    stream between this start's lookup and its own write.
    """

    def __init__(self) -> None:
        super().__init__(
            EventStoreRepository(
                MemoryEventStoreClient(),
                ExecutionRequestAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                "ExecutionRequest",
            )
        )
        self.misses = 0

    async def get_by_id(self, aggregate_id: str) -> ExecutionRequestAggregate | None:
        if self.misses:
            self.misses -= 1
            return None
        return await super().get_by_id(aggregate_id)


class _Api:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _noop_connect() -> None:
            return None

        self.maintenance = InMemoryMaintenanceAdapter()
        self.starts = _Starts()
        self.requests = _Requests()
        monkeypatch.setattr(
            admission,
            "_admission_gate_singleton",
            AdmissionGate(self.maintenance),
            raising=False,
        )
        monkeypatch.setattr(commands, "ensure_connected", _noop_connect)
        monkeypatch.setattr(commands, "get_workflow_repo", _WorkflowRepo)
        monkeypatch.setattr(commands, "execute", self.starts)
        monkeypatch.setattr(repositories, "get_execution_request_repository", lambda: self.requests)

    async def post(self, request: ExecuteWorkflowRequest) -> ExecuteWorkflowResponse:
        tasks = BackgroundTasks()
        response = await commands.execute_workflow_endpoint(WORKFLOW_ID, request, tasks)
        await tasks()
        return response


def _keyed(**changed: str) -> ExecuteWorkflowRequest:
    return ExecuteWorkflowRequest(
        task=changed.get("task", "score the case"),
        repos=[REPO],
        tags=TagSet([KEY]),
        idempotency_key=changed.get("idempotency_key", KEY),
    )


class TestAKeyedRetryStartsNothing:
    @pytest.mark.asyncio
    async def test_the_retry_answers_with_the_first_execution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api = _Api(monkeypatch)
        first = await api.post(_keyed())
        retry = await api.post(_keyed())

        assert first.execution_id == execution_id_for_key(WORKFLOW_ID, KEY)
        assert retry.execution_id == first.execution_id
        assert (first.replayed, retry.replayed) == (False, True)
        assert api.starts.ids == [first.execution_id]

    @pytest.mark.asyncio
    async def test_a_concurrent_start_that_lost_the_stream_answers_with_the_winner(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api = _Api(monkeypatch)
        first = await api.post(_keyed())
        # The racing start's lookup ran before the winner's write landed.
        api.requests.misses = 1
        racer = await api.post(_keyed())

        assert racer.execution_id == first.execution_id
        assert racer.replayed
        assert api.starts.ids == [first.execution_id]

    @pytest.mark.asyncio
    async def test_a_racer_that_reused_the_key_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api = _Api(monkeypatch)
        await api.post(_keyed())
        api.requests.misses = 1
        with pytest.raises(HTTPException) as refused:
            await api.post(_keyed(task="another case"))

        assert refused.value.status_code == 409
        assert len(api.starts.ids) == 1

    @pytest.mark.asyncio
    async def test_a_retry_during_maintenance_hears_about_its_start(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api = _Api(monkeypatch)
        first = await api.post(_keyed())
        await api.maintenance.set_mode(active=True, reason="deploy", actor="test")

        retry = await api.post(_keyed())

        assert retry.execution_id == first.execution_id
        assert retry.replayed
        with pytest.raises(HTTPException) as paused:
            await api.post(_keyed(idempotency_key="trial:b2129/2"))
        assert paused.value.status_code == 409
        assert api.starts.ids == [first.execution_id]


class TestAReusedKeyIsRefused:
    @pytest.mark.asyncio
    async def test_a_different_request_under_the_key_is_409_and_starts_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api = _Api(monkeypatch)
        first = await api.post(_keyed())
        with pytest.raises(HTTPException) as refused:
            await api.post(_keyed(task="another case"))

        assert refused.value.status_code == 409
        assert first.execution_id in str(refused.value.detail)
        assert api.starts.ids == [first.execution_id]

    @pytest.mark.asyncio
    async def test_two_keys_that_share_an_id_are_never_a_replay(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The request records its key: a colliding key is compared, not trusted (codex #2155).
        api = _Api(monkeypatch)
        monkeypatch.setattr(keyed_start, "execution_id_for_key", lambda _w, _k: "exec-collide")
        first = await api.post(_keyed())
        with pytest.raises(HTTPException) as refused:
            await api.post(_keyed(idempotency_key="trial:b2129/2"))

        assert refused.value.status_code == 409
        assert api.starts.ids == [first.execution_id]


class TestKeysAreIndependent:
    @pytest.mark.asyncio
    async def test_two_keys_are_two_starts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        api = _Api(monkeypatch)
        one = await api.post(_keyed())
        two = await api.post(_keyed(idempotency_key="trial:b2129/2"))

        assert one.execution_id != two.execution_id
        assert not two.replayed
        assert api.starts.ids == [one.execution_id, two.execution_id]

    @pytest.mark.asyncio
    async def test_an_unkeyed_start_is_never_a_replay(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api = _Api(monkeypatch)
        request = ExecuteWorkflowRequest(task="score the case", repos=[REPO])
        one = await api.post(request)
        two = await api.post(request)

        assert one.execution_id != two.execution_id
        assert (one.replayed, two.replayed) == (False, False)
        assert len(api.starts.ids) == 2

    @pytest.mark.asyncio
    async def test_the_first_keyed_start_records_its_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api = _Api(monkeypatch)
        started = await api.post(_keyed())
        recorded = await api.requests.get_by_id(execution_request_id(started.execution_id))

        assert recorded is not None
        assert recorded.workflow_id == WORKFLOW_ID


class TestTheKeyIsValidated:
    @pytest.mark.parametrize("key", ["", "a\x00b", "k" * 201])
    def test_an_unusable_key_is_a_validation_error(self, key: str) -> None:
        with pytest.raises(ValidationError, match="idempotency_key"):
            ExecuteWorkflowRequest(idempotency_key=key)

    def test_eval_id_with_no_eval_is_a_validation_error(self) -> None:
        # On the model, so a keyed retry is a 422 before its replay lookup, not a 500.
        with pytest.raises(ValidationError, match="not both"):
            ExecuteWorkflowRequest(idempotency_key=KEY, eval_id=EvalId("eval-2129"), no_eval=True)

    def test_the_longest_key_is_accepted(self) -> None:
        assert ExecuteWorkflowRequest(idempotency_key="k" * 200).idempotency_key == "k" * 200
