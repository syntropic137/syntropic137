"""The run-queue flag's wiring (#1310 1.3): OFF is today's path, ON never spawns.

OFF must not touch the run queue at all - not build one, not reach for
Postgres - because nothing claims an admitted run until #1310 1.5. ON must
refuse to run without Postgres (ADR-060) and must start inline, so no task
carries an execution (V11).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_api import _wiring, _wiring_db
from syn_api._wiring_admission import BackgroundWorkflowDispatcher
from syn_api.routes.executions import commands
from syn_api.types import Err, ExecutionSummary, Ok, WorkflowError
from syn_domain.contexts._shared import AdmissionGate
from syn_domain.contexts.orchestration import TagSet, WorkflowTemplateAggregate
from syn_shared.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


@pytest.fixture
def run_queue_flag(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SYN_EXECUTION_RUN_QUEUE_ENABLED", "true")
    monkeypatch.setattr(_wiring, "_run_queue_singleton", None)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    monkeypatch.delenv("SYN_EXECUTION_RUN_QUEUE_ENABLED")
    get_settings.cache_clear()  # type: ignore[attr-defined]


async def test_off_builds_no_run_queue_and_never_asks_for_a_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_settings.cache_clear()  # type: ignore[attr-defined]
    assert get_settings().execution.run_queue_enabled is False
    pool = MagicMock(side_effect=AssertionError("the OFF path reached for Postgres"))
    monkeypatch.setattr(_wiring_db, "get_shared_db_pool", pool)

    assert await _wiring.get_execution_run_queue() is None
    pool.assert_not_called()


@pytest.mark.usefixtures("run_queue_flag")
async def test_on_without_postgres_refuses_rather_than_queue_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_wiring_db, "get_shared_db_pool", lambda: None)

    with pytest.raises(RuntimeError, match="never falls back to memory"):
        await _wiring.get_execution_run_queue()


async def test_on_a_trigger_start_is_awaited_inline_and_spawns_no_task() -> None:
    handler = MagicMock()
    handler.validate_stored_declarations = AsyncMock()
    handled = asyncio.Event()

    async def handle(_command: object, *, admitted: object = None) -> None:
        handled.set()

    handler.handle = handle
    dispatcher = BackgroundWorkflowDispatcher(handler, admits_to_run_queue=True)
    tasks_before = asyncio.all_tasks()

    await dispatcher.run_workflow("wf-1", {"task": "x"}, execution_id="exec-inline")

    assert handled.is_set(), "the start must have run before run_workflow returned"
    assert asyncio.all_tasks() == tasks_before
    assert dispatcher.budget.position("exec-inline") is None


async def test_off_a_trigger_start_is_still_spawned() -> None:
    handler = MagicMock()
    handler.validate_stored_declarations = AsyncMock()
    gate = asyncio.Event()

    async def handle(_command: object, *, admitted: object = None) -> None:
        await gate.wait()

    handler.handle = handle
    dispatcher = BackgroundWorkflowDispatcher(handler)

    await dispatcher.run_workflow("wf-1", {"task": "x"}, execution_id="exec-spawned")

    assert dispatcher.holds_execution("exec-spawned")
    gate.set()
    await dispatcher.shutdown()


class _Request:
    """Enough of ExecuteWorkflowRequest for the endpoint's signature."""

    inputs: ClassVar[dict[str, str]] = {}
    repos: ClassVar[list[str]] = ["https://github.com/syntropic137/syntropic137"]
    task: str | None = None
    tags = TagSet()
    eval_id: None = None
    no_eval = False
    provider = "claude"


class _WorkflowRepo:
    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate:
        del aggregate_id
        return WorkflowTemplateAggregate()


async def _nothing_to_connect() -> None:
    return None


def _route_admission_returning(
    monkeypatch: pytest.MonkeyPatch, result: Ok[ExecutionSummary] | Err[WorkflowError]
) -> list[str]:
    """Wire `POST /execute` around an `execute` that answers `result` inline."""
    import syn_api._wiring_admission as wiring

    started: list[str] = []

    async def execute(*, execution_id: str, **_kwargs: object) -> object:
        started.append(execution_id)
        return result

    monkeypatch.setattr(
        wiring,
        "_admission_gate_singleton",
        AdmissionGate(InMemoryMaintenanceAdapter()),
        raising=False,
    )
    monkeypatch.setattr(commands, "ensure_connected", _nothing_to_connect)
    monkeypatch.setattr(commands, "get_workflow_repo", _WorkflowRepo)
    monkeypatch.setattr(commands, "execute", execute)
    return started


@pytest.mark.usefixtures("run_queue_flag")
async def test_on_a_direct_start_that_was_not_admitted_is_not_a_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ON, the start has happened or failed before the route answers, so a
    failed reserve/open/mark_admitted must be the caller's answer, never a
    log line behind ``status="started"``."""
    started = _route_admission_returning(
        monkeypatch,
        Err(WorkflowError.EXECUTION_FAILED, message="run queue refused the reserve"),
    )
    tasks = BackgroundTasks()

    with pytest.raises(HTTPException) as refused:
        await commands.execute_workflow_endpoint(
            "wf-1",
            _Request(),  # type: ignore[arg-type]
            tasks,
        )

    assert refused.value.status_code == 500
    assert "run queue refused the reserve" in str(refused.value.detail)
    assert len(started) == 1, "the start must have been attempted inline"
    assert tasks.tasks == [], "ON must not queue a background task (V11)"


@pytest.mark.usefixtures("run_queue_flag")
async def test_on_an_admitted_direct_start_answers_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = ExecutionSummary.model_construct(
        workflow_execution_id="exec-x", workflow_id="wf-1", status="admitted"
    )
    started = _route_admission_returning(monkeypatch, Ok(summary))
    tasks = BackgroundTasks()

    response = await commands.execute_workflow_endpoint(
        "wf-1",
        _Request(),  # type: ignore[arg-type]
        tasks,
    )

    assert response.status == "started"
    assert started == [response.execution_id]
    assert tasks.tasks == []
