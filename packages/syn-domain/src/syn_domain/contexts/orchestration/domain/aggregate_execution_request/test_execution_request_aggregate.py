"""An execution request carries everything its start needs through storage (#1557)."""

from __future__ import annotations

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration._shared.eval_choice import EvalSelection, LaunchEval
from syn_domain.contexts.orchestration._shared.repository_baseline import RepositoryBaseline
from syn_domain.contexts.orchestration._shared.tags import TagSet
from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import EvalId
from syn_domain.contexts.orchestration.domain.aggregate_execution_request import (
    ExecutionAlreadyRequestedError,
    ExecutionRequestAggregate,
    execution_request_id,
)
from syn_domain.contexts.orchestration.domain.commands.RequestExecutionCommand import (
    RequestExecutionCommand,
)

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


_PINNED = (
    RepositoryBaseline(
        repository=RepositoryRef.from_slug("acme/widgets"),
        requested_ref="main",
        commit_sha="c3" * 20,
    ),
)


def _command(launch: LaunchEval) -> RequestExecutionCommand:
    return RequestExecutionCommand(
        execution_id="exec-1557req",
        workflow_id="wf-1557",
        inputs={"task": "do it"},
        task="do it",
        repos=[RepositoryRef.from_slug("acme/widgets")],
        tags=TagSet(["team-a"]),
        launch_eval=launch,
    )


@pytest.mark.parametrize(
    "launch",
    [
        LaunchEval(None, EvalSelection.NONE),
        LaunchEval(EvalId("eval-1557"), EvalSelection.EXPLICIT, _PINNED),
        LaunchEval(EvalId("eval-default"), EvalSelection.WORKFLOW_DEFAULT, _PINNED),
        LaunchEval(None, EvalSelection.ORDINARY),
    ],
    ids=["none", "explicit", "workflow-default", "ordinary"],
)
async def test_a_stored_request_reads_back_the_eval_it_was_accepted_into(
    launch: LaunchEval,
) -> None:
    repo = RepositoryAdapter(
        EventStoreRepository(
            MemoryEventStoreClient(),
            ExecutionRequestAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "ExecutionRequest",
        )
    )
    request = ExecutionRequestAggregate()
    request.request(_command(launch))
    await repo.save_new(request)

    loaded = await repo.get_by_id(execution_request_id("exec-1557req"))

    assert loaded is not None
    assert loaded.workflow_id == "wf-1557"
    assert loaded.inputs == {"task": "do it"}
    assert loaded.task == "do it"
    assert loaded.repos == [RepositoryRef.from_slug("acme/widgets")]
    assert list(loaded.tags) == ["team-a"]
    # Resolved at acceptance and read back whole, baseline SHAs included (#967).
    assert loaded.launch_eval == launch
    assert loaded.requested_at is not None


def test_an_execution_id_is_requested_once() -> None:
    request = ExecutionRequestAggregate()
    request.request(_command(LaunchEval(None, EvalSelection.NONE)))
    with pytest.raises(ExecutionAlreadyRequestedError):
        request.request(_command(LaunchEval(None, EvalSelection.NONE)))


def test_a_request_never_takes_its_executions_id() -> None:
    """The event store keys a stream by aggregate id alone, whatever its type.

    A request at the execution's id became version 1 of that execution's
    stream on the server, and every direct start was then refused as a
    duplicate (v0.33.2-beta.8/beta.9).
    """
    request = ExecutionRequestAggregate()
    request.request(_command(LaunchEval(None, EvalSelection.NONE)))

    assert request.id == execution_request_id("exec-1557req")
    assert request.id != "exec-1557req"
