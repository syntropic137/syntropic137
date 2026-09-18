"""#1307: an execution can say what it was asked to do.

`GET /executions/{id}` reported repos, phases, tokens and cost, and nothing at
all about the request that produced them. An operator retrying a run that died
on the platform (#1293, #1295) had to reconstruct the task and the inputs from
their own notes, because the platform that ran it could not tell them.

WHERE IT WAS DROPPED, since the issue asks. Not on the write side: the dispatch
folds the task into `inputs` and `WorkflowExecutionStartedEvent.inputs` carries
the merged dict as a first-class Lane 1 field, so it was in the event store the
whole time. `WorkflowExecutionDetailProjection` read that dict for the `repos`
key alone and threw the rest away.

WHY THE TESTS START AT THE COMMAND. The task is not a field the event has - it
arrives as `ExecuteWorkflowCommand.task` and is folded into `inputs` under a
key, and the read side has to look under the SAME key. Two constants agreeing
today is exactly the hop that goes quiet later, so the fixtures are driven from
`ExecuteWorkflowHandler._merge_inputs` rather than from a hand-written dict
that would keep passing after the fold moved.

Between the command and the response there are five more hops that each re-list
their fields by hand - the projection dict, `WorkflowExecutionDetail`,
`ExecutionDetailFull`, `ExecutionDetail` and `ExecutionDetailResponse` - and
this repository has lost a field at such a hop three times (#891, #1176, #1300).
So nothing here asserts on the object it just built.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    InputDeclaration,
)
from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
    ExecuteWorkflowCommand,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

if TYPE_CHECKING:
    from syn_api.routes.executions.models import ExecutionDetailResponse
    from syn_api.types import ExecutionDetail

pytestmark = pytest.mark.unit

EXECUTION_ID = "exec-1307-dispatch"
WORKFLOW_ID = "wf-sdlc-fix"
_STARTED_AT = datetime(2026, 9, 17, 9, 0, tzinfo=UTC)

#: The $ARGUMENTS this run was dispatched with. Long and specific on purpose:
#: no default, no fixture and no placeholder anywhere in the chain produces it,
#: so it can only have arrived by being carried the whole way.
TASK = "Fix #1307: an execution record does not say what it was asked to do"

#: What the caller passed alongside the task. `repos` is here because the
#: projection already reads it out of this same dict, and keeping it is what
#: makes the record re-dispatchable rather than nearly re-dispatchable.
CALLER_INPUTS = {
    "repos": "https://github.com/syntropic137/syntropic137",
    "issue_number": "1307",
}

#: An input the caller never sent. It exists only because the workflow declared
#: a default, which means a response carrying it proves the response shows what
#: the run ACTUALLY ran with and not a copy of the caller's request.
DECLARED_DEFAULT = InputDeclaration(name="reviewer_model", required=False, default="opus-5")


@dataclass(frozen=True)
class _WorkflowWithDeclarations:
    """The only part of a workflow template `_merge_inputs` reads."""

    input_declarations: list[InputDeclaration] = field(default_factory=list)


def _dispatched_inputs(task: str | None) -> dict[str, str]:
    """The inputs a dispatch actually writes, produced by the real fold.

    Calling the handler's own merge instead of restating its output: the key
    the task lands under is the thing under test, and a literal here would
    agree with itself forever.
    """
    return ExecuteWorkflowHandler._merge_inputs(  # pyright: ignore[reportPrivateUsage]
        ExecuteWorkflowCommand(
            aggregate_id=WORKFLOW_ID,
            execution_id=EXECUTION_ID,
            inputs=dict(CALLER_INPUTS),
            task=task,
        ),
        _WorkflowWithDeclarations([DECLARED_DEFAULT]),  # pyright: ignore[reportArgumentType]
    )


def _started(
    task: str | None, inputs: dict[str, str] | None = None
) -> WorkflowExecutionStartedEvent:
    return WorkflowExecutionStartedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=EXECUTION_ID,
        workflow_name="implement-verify-report",
        started_at=_STARTED_AT,
        total_phases=3,
        inputs=_dispatched_inputs(task) if inputs is None else inputs,
    )


@dataclass
class _StubProjectionManager:
    """What the detail read path reads. Cost and tool lookups fail soft."""

    store: InMemoryProjectionStore
    workflow_execution_detail: WorkflowExecutionDetailProjection


async def _read_path(
    monkeypatch: pytest.MonkeyPatch, task: str | None, inputs: dict[str, str] | None = None
) -> _StubProjectionManager:
    """Drive the real projection from a real start event and wire the routes."""
    from syn_api import _wiring
    from syn_api.routes.executions import queries

    store = InMemoryProjectionStore()
    projection = WorkflowExecutionDetailProjection(store)
    await projection.on_workflow_execution_started(_started(task, inputs).model_dump())

    manager = _StubProjectionManager(store=store, workflow_execution_detail=projection)

    async def _noop_connect() -> None:
        return None

    monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: manager)
    return manager


async def _served(
    monkeypatch: pytest.MonkeyPatch,
    task: str | None = TASK,
    inputs: dict[str, str] | None = None,
) -> ExecutionDetailResponse:
    """`GET /executions/{id}` as an API client receives it."""
    from syn_api.routes.executions import queries

    await _read_path(monkeypatch, task, inputs)
    return await queries.get_execution_endpoint(EXECUTION_ID)


async def _summary_dto(monkeypatch: pytest.MonkeyPatch, task: str | None = TASK) -> ExecutionDetail:
    """The other execution-detail DTO, built by `queries.get`."""
    from syn_api.routes.executions import queries

    await _read_path(monkeypatch, task)
    result = await queries.get(EXECUTION_ID)
    assert not isinstance(result, Exception)
    return result.value


@pytest.mark.asyncio
async def test_the_task_a_run_was_dispatched_with_reaches_the_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The question the issue asks, answered where a client reads it."""
    response = await _served(monkeypatch)

    assert response.task == TASK, (
        f"an execution served task={response.task!r} for a run dispatched with "
        f"{TASK!r}; a failed run cannot be retried from the platform (#1307)"
    )


@pytest.mark.asyncio
async def test_the_inputs_reach_the_response_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every key, including the ones other fields are derived from.

    Asserted as the whole mapping rather than key by key: a hop that forwarded
    the task and dropped `issue_number`, or one that edited out `repos` because
    the response already has a `repos` field, leaves a record that reads
    complete and cannot be re-dispatched - which is the failure this field
    exists to prevent, one level quieter.
    """
    response = await _served(monkeypatch)

    assert response.inputs == {
        "repos": "https://github.com/syntropic137/syntropic137",
        "issue_number": "1307",
        "reviewer_model": "opus-5",
        "task": TASK,
    }


@pytest.mark.asyncio
async def test_a_default_the_caller_never_sent_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The response shows what the run ran with, not what was requested.

    `reviewer_model` was never in the caller's inputs; the workflow's own
    declaration put it there. A view that echoed the request back would be
    wrong about exactly the inputs a retry most needs to reproduce.
    """
    response = await _served(monkeypatch)

    assert "reviewer_model" not in CALLER_INPUTS
    assert response.inputs["reviewer_model"] == "opus-5"


@pytest.mark.asyncio
async def test_a_run_dispatched_without_a_task_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Null is an answer, and it is a different answer.

    Paired with the first test deliberately. A workflow whose phases take no
    `$ARGUMENTS` is dispatched with no task, and reporting `""` for it would
    make "asked nothing" read the same as "nobody recorded what it was asked" -
    the state this issue is about.
    """
    response = await _served(monkeypatch, task=None)

    assert response.task is None
    assert "task" not in response.inputs
    assert response.inputs["issue_number"] == "1307", "the other inputs still travel"


@pytest.mark.asyncio
async def test_the_other_detail_dto_carries_them_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`queries.get` builds a second detail DTO off the same read model.

    Two constructor calls, two chances to drop a field. This one is not behind
    a route today, so a defect here would surface as a fresh regression the
    first time it is wired - the cheapest possible bug to prevent now.
    """
    detail = await _summary_dto(monkeypatch)

    assert detail.task == TASK
    assert detail.inputs["issue_number"] == "1307"


@pytest.mark.asyncio
async def test_repos_are_still_derived_from_the_kept_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keeping the dict did not disturb the one key that was already read."""
    response = await _served(monkeypatch)

    assert response.repos == ["https://github.com/syntropic137/syntropic137"]


@pytest.mark.asyncio
async def test_a_run_dispatched_with_no_repos_still_reports_its_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No `repos` input reads back as no repos, not as one empty-string repo.

    Pins the removal of the `if repos_raw else []` guard the projection used to
    carry. `"".split(",")` is `[""]`, so it is the truthiness filter and not the
    guard that empties this; the guard was a special case that decided nothing,
    and this is what makes its absence safe rather than merely untested.

    Read off the served response, because the guard sat upstream of five hops
    that each re-list their fields by hand.
    """
    no_repos = ExecuteWorkflowHandler._merge_inputs(  # pyright: ignore[reportPrivateUsage]
        ExecuteWorkflowCommand(
            aggregate_id=WORKFLOW_ID,
            execution_id=EXECUTION_ID,
            inputs={"issue_number": "1307"},
            task=TASK,
        ),
        _WorkflowWithDeclarations([DECLARED_DEFAULT]),  # pyright: ignore[reportArgumentType]
    )
    assert "repos" not in no_repos

    response = await _served(monkeypatch, inputs=no_repos)

    assert response.repos == []
    assert response.task == TASK
    assert response.inputs == no_repos
