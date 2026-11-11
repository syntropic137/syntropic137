"""#1075: each execution's task reaches the list, so runs of one workflow read apart.

The detail has served `task` since #1307; the list did not, so every run of a
workflow showed an identical row. These replay real `WorkflowExecutionStarted`
events into the real projections and call the real route functions, so a read
model that does not keep the task, a constructor that does not pass it, or a
response model that does not declare it, all fail here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    TASK_INPUT_KEY,
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)

if TYPE_CHECKING:
    from syn_api.routes.executions.models import ExecutionSummaryResponse

pytestmark = pytest.mark.unit

WORKFLOW_ID = "wf-1075"
LONG_TASK = "Fix the flaky login test\n\nthen   " + "explain the root cause " * 6
TASKS: dict[str, str | None] = {
    "exec-login-1075": LONG_TASK,
    "exec-darkmode-1075": "Add dark mode",
    "exec-untasked-1075": None,
}


@dataclass
class _StubProjectionManager:
    store: InMemoryProjectionStore
    workflow_execution_detail: WorkflowExecutionDetailProjection
    workflow_execution_list: WorkflowExecutionListProjection


async def _serve(monkeypatch: pytest.MonkeyPatch) -> None:
    from syn_api import _wiring
    from syn_api.routes.executions import queries

    store = InMemoryProjectionStore()
    detail = WorkflowExecutionDetailProjection(store)
    listing = WorkflowExecutionListProjection(store)
    for execution_id, task in TASKS.items():
        started = WorkflowExecutionStartedEvent(
            workflow_id=WORKFLOW_ID,
            execution_id=execution_id,
            workflow_name="one workflow",
            started_at=datetime(2026, 11, 11, 9, 0, tzinfo=UTC),
            total_phases=1,
            # Folded into the inputs exactly as the handler folds it (#1307),
            # beside an input the list must not carry.
            inputs={"secret_ish": "author text"} | ({} if task is None else {TASK_INPUT_KEY: task}),
        ).model_dump()
        for projection in (detail, listing):
            await projection.on_workflow_execution_started(started)
    manager = _StubProjectionManager(
        store=store, workflow_execution_detail=detail, workflow_execution_list=listing
    )

    async def _noop_connect() -> None:
        return None

    monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: manager)


async def _listed() -> dict[str, ExecutionSummaryResponse]:
    """`GET /executions`, as execution id -> the row the route returns."""
    from syn_api.routes.executions import queries

    # Every parameter explicit: called outside FastAPI, `Query(...)` defaults
    # arrive as `Query` objects rather than the values they describe.
    response = await queries.list_executions_endpoint(
        status=None,
        statuses=None,
        started_after=None,
        started_before=None,
        q=None,
        tag=None,
        eval_id=None,
        in_eval=None,
        review_verdict=None,
        page=1,
        page_size=50,
    )
    return {e.workflow_execution_id: e for e in response.executions if e.workflow_id == WORKFLOW_ID}


async def test_runs_of_one_workflow_list_their_own_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    await _serve(monkeypatch)
    rows = await _listed()

    assert rows["exec-darkmode-1075"].task == "Add dark mode"
    assert rows["exec-darkmode-1075"].task_display == "Add dark mode"
    assert rows["exec-login-1075"].task == LONG_TASK
    display = rows["exec-login-1075"].task_display
    assert isinstance(display, str)
    assert display.startswith("Fix the flaky login test then explain the root cause")
    assert display.endswith("…")
    assert "\n" not in display
    assert len(display) <= 80


async def test_a_run_dispatched_without_a_task_lists_none(monkeypatch: pytest.MonkeyPatch) -> None:
    await _serve(monkeypatch)
    row = (await _listed())["exec-untasked-1075"]

    assert row.task is None
    assert row.task_display is None


async def test_the_list_carries_the_task_and_never_the_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _serve(monkeypatch)
    row = (await _listed())["exec-login-1075"]

    wire = row.model_dump_json()
    assert '"inputs"' not in wire
    assert "author text" not in wire


async def test_the_list_and_the_detail_report_the_same_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.routes.executions import queries

    await _serve(monkeypatch)
    rows = await _listed()
    for execution_id in TASKS:
        detail = await queries.get_execution_endpoint(execution_id)
        assert rows[execution_id].task == detail.task, execution_id


async def test_a_non_string_task_lists_as_the_detail_shows_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The aggregate admits any input value; the list reads it as the detail does.

    Driven through the real producer: `StartExecutionCommand.inputs` is not
    narrowed to strings, so a task of `42` is written to the event as a number.
    The detail has always shown it as `"42"`; a list projection reading inputs
    raw failed to build the row, and one such row fails the whole list.
    """
    import json

    from syn_api.routes.executions import queries
    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        StartExecutionCommand,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )

    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id="exec-numeric-1075",
            workflow_id=WORKFLOW_ID,
            workflow_name="one workflow",
            total_phases=1,
            inputs={TASK_INPUT_KEY: 42},
        )
    )
    # As the store hands it back: serialised, then read.
    started = json.loads(aggregate.get_uncommitted_events()[0].event.model_dump_json())
    assert started["inputs"][TASK_INPUT_KEY] == 42

    await _serve(monkeypatch)
    manager = queries.get_projection_mgr()
    for projection in (manager.workflow_execution_detail, manager.workflow_execution_list):
        await projection.on_workflow_execution_started(started)

    rows = await _listed()
    detail = await queries.get_execution_endpoint("exec-numeric-1075")
    assert detail.task == "42"
    assert rows["exec-numeric-1075"].task == detail.task
    assert rows["exec-numeric-1075"].task_display == "42"
    # The rest of the list is still served beside it.
    assert rows["exec-darkmode-1075"].task == "Add dark mode"
