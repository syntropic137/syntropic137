"""An execution request carries everything its start needs through storage (#1557)."""

from __future__ import annotations

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration._shared.eval_choice import EvalChoice
from syn_domain.contexts.orchestration._shared.tags import TagSet
from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import EvalId
from syn_domain.contexts.orchestration.domain.aggregate_execution_request import (
    ExecutionAlreadyRequestedError,
    ExecutionRequestAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.RequestExecutionCommand import (
    RequestExecutionCommand,
)

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


def _command(choice: EvalChoice) -> RequestExecutionCommand:
    return RequestExecutionCommand(
        execution_id="exec-1557req",
        workflow_id="wf-1557",
        inputs={"task": "do it"},
        task="do it",
        repos=[RepositoryRef.from_slug("acme/widgets")],
        tags=TagSet(["team-a"]),
        eval_choice=choice,
    )


@pytest.mark.parametrize(
    "choice",
    [EvalChoice(), EvalChoice(eval_id=EvalId("eval-1557")), EvalChoice(ordinary=True)],
    ids=["default", "explicit", "ordinary"],
)
async def test_a_stored_request_reads_back_what_was_asked(choice: EvalChoice) -> None:
    repo = RepositoryAdapter(
        EventStoreRepository(
            MemoryEventStoreClient(),
            ExecutionRequestAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "ExecutionRequest",
        )
    )
    request = ExecutionRequestAggregate()
    request.request(_command(choice))
    await repo.save_new(request)

    loaded = await repo.get_by_id("exec-1557req")

    assert loaded is not None
    assert loaded.workflow_id == "wf-1557"
    assert loaded.inputs == {"task": "do it"}
    assert loaded.task == "do it"
    assert loaded.repos == [RepositoryRef.from_slug("acme/widgets")]
    assert list(loaded.tags) == ["team-a"]
    assert loaded.eval_choice == choice
    assert loaded.requested_at is not None


def test_an_execution_id_is_requested_once() -> None:
    request = ExecutionRequestAggregate()
    request.request(_command(EvalChoice()))
    with pytest.raises(ExecutionAlreadyRequestedError):
        request.request(_command(EvalChoice()))
