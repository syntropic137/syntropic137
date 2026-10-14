"""An admitted run survives a process restart through production startup (#1310 1.5; verify B1).

Real Postgres Run Queue and the real event store, wired as in
``test_1310_a_claimed_three_phase_run_succeeds_on_real_stores``. The previous
process admits a start and is discarded before anything claims it. The new
process then runs the two production startup entrypoints ``lifecycle`` calls,
``resolve_previous_process`` and ``start_execution_host``, unchanged. Only the
process-wide getters they read are pointed at the test stores, and the
docker-backed startup reaps are recorders.

* ON: the global reap and reconcile do not run, the host claims the admitted
  run and drains it: exactly one ``WorkflowExecutionStarted``, one terminal
  ``WorkflowCompleted``, no ``WorkflowFailed`` (no OrphanedByRestart).
* OFF: the global reap and reconcile run, in order, and no host is built.

What this does NOT run is the FastAPI lifespan itself; that ``lifecycle`` calls
these entrypoints in this order is pinned by
``test_execution_host_runner_is_dark_with_the_flag_off``.

Run: ``uv run pytest -m integration apps/syn-api/tests/integration/test_1310_an_admitted_run_survives_a_restart_through_production_startup.py``
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.storage.repositories import EventStoreExecutionEventStream
from syn_api.services import execution_host_runner, unlabelled_containers
from syn_domain.testing.fake_agent_handler import A_DELIVERABLE, FakeAgentExecutionHandler
from syn_shared.settings import get_settings

from .test_1310_a_claimed_three_phase_run_succeeds_on_real_stores import (  # noqa: F401  # fixtures
    _Infra,
    _start,
    infra,
    pool,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    import asyncpg

pytestmark = pytest.mark.integration

#: Far above the ~1s the drain takes; only a host that never claims reaches it.
_DRAIN_BUDGET_SECONDS = 60


@pytest.fixture
def flag(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


async def _wire(monkeypatch: pytest.MonkeyPatch, world: _Infra, *, enabled: bool) -> list[str]:
    """Point the runner's getters at ``world``; return the global-startup recorder."""
    monkeypatch.setenv("SYN_EXECUTION_RUN_QUEUE_ENABLED", "true" if enabled else "false")
    get_settings.cache_clear()
    calls: list[str] = []

    async def _cleanup() -> object:
        calls.append("cleanup_orphaned_containers")
        return object()

    async def _reconcile(*_args: object, **_kwargs: object) -> None:
        calls.append("reconcile_orphaned_executions")

    async def _no_unlabelled() -> list[str]:
        return []

    async def _queue() -> object:
        return world.queue if get_settings().execution.run_queue_enabled else None

    drainer, _ = await world.processor(
        FakeAgentExecutionHandler.success(produces=A_DELIVERABLE), queued=True
    )
    executions = await world.executions()
    streams = EventStoreExecutionEventStream(await world.client())

    async def _processor() -> object:
        calls.append("get_execution_processor")
        return drainer

    monkeypatch.setattr(execution_host_runner, "cleanup_orphaned_containers", _cleanup)
    monkeypatch.setattr(execution_host_runner, "reconcile_orphaned_executions", _reconcile)
    monkeypatch.setattr(unlabelled_containers, "_unlabelled_ids", _no_unlabelled)
    monkeypatch.setattr(execution_host_runner, "get_execution_run_queue", _queue)
    monkeypatch.setattr(execution_host_runner, "get_execution_processor", _processor)
    monkeypatch.setattr(
        execution_host_runner, "get_workflow_execution_repository", lambda: executions
    )
    monkeypatch.setattr(execution_host_runner, "get_execution_event_stream", lambda: streams)
    return calls


async def _admitted_by_a_process_that_then_dies(world: _Infra) -> str:
    execution_id = f"exec-{uuid4().hex[:12]}"
    admitting, _ = await world.processor(
        FakeAgentExecutionHandler.success(produces=A_DELIVERABLE), queued=True
    )
    assert await _start(admitting, execution_id) == "admitted"
    del admitting
    assert await world.event_types(execution_id) == ["WorkflowExecutionStarted"]
    assert (await world.queue.in_use()).admitted == 1
    return execution_id


async def test_flag_on_a_restarted_process_claims_and_completes_the_admitted_run(
    infra: _Infra,  # noqa: F811
    pool: asyncpg.Pool,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    flag: None,
) -> None:
    execution_id = await _admitted_by_a_process_that_then_dies(infra)
    calls = await _wire(monkeypatch, infra, enabled=True)

    await execution_host_runner.resolve_previous_process(started_before=datetime.now(UTC))
    await execution_host_runner.start_execution_host()
    try:
        async with asyncio.timeout(_DRAIN_BUDGET_SECONDS):
            while (await infra.queue.in_use()).done != 1:
                await asyncio.sleep(0.2)
    finally:
        await execution_host_runner.stop_execution_host()

    assert calls == ["get_execution_processor"]  # neither global startup op ran
    types = await infra.event_types(execution_id)
    assert types.count("WorkflowExecutionStarted") == 1, types
    assert "WorkflowFailed" not in types, types
    assert types[-1] == "WorkflowCompleted", types
    counts = await infra.queue.in_use()
    assert (counts.admitted, counts.claimed, counts.done) == (0, 0, 1)
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM executor_hosts") == 0  # deregistered


async def test_flag_off_startup_is_mains_and_builds_no_host(
    infra: _Infra,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    flag: None,
) -> None:
    calls = await _wire(monkeypatch, infra, enabled=False)

    await execution_host_runner.resolve_previous_process(started_before=datetime.now(UTC))
    await execution_host_runner.start_execution_host()

    assert calls == ["cleanup_orphaned_containers", "reconcile_orphaned_executions"]
    assert execution_host_runner._host_task is None  # the runner's only state
    assert (await infra.queue.in_use()).claimed == 0
