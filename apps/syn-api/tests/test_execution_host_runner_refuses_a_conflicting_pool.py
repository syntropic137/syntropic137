"""A pool this process may not join refuses startup (ADR-072 D13).

Driven through the real ``ExecutionHost`` and the in-memory Run Queue's real
registration rule, with another executor already live in the pool: the
conflict must reach ``start_execution_host``'s caller, which is what aborts
startup, rather than end a background task after startup reported success.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.execution_runs.memory import InMemoryExecutionRunQueue
from syn_adapters.workspace_backends.host_labels import LABEL_HOST_ID, host_labels
from syn_api.services import execution_host_runner as runner
from syn_domain.contexts.orchestration.ports import (
    ExecutorHost,
    ExecutorPool,
    PoolDefinitionConflict,
)
from syn_shared.settings import reset_settings

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_LIVE = "live-member"
_ENGINE = "engine-1"


async def _queue_with_a_live_member(monkeypatch: pytest.MonkeyPatch) -> InMemoryExecutionRunQueue:
    queue = InMemoryExecutionRunQueue()
    member = ExecutorHost(
        host_id=_LIVE,
        container_id="another-box",
        generation="g1",
        epoch=1,
        reap_scope="engine-1",
        pool=ExecutorPool(pool_id="review", priority=1, provider="docker"),
    )
    await queue.register(member, 1)
    monkeypatch.setenv("SYN_EXECUTION_RUN_QUEUE_ENABLED", "true")
    monkeypatch.setenv("SYN_EXECUTOR_POOL_ID", "review")
    monkeypatch.setattr(runner, "get_execution_run_queue", AsyncMock(return_value=queue))
    monkeypatch.setattr(runner, "get_execution_processor", AsyncMock())
    monkeypatch.setattr(runner, "get_workflow_execution_repository", MagicMock())
    monkeypatch.setattr(runner, "get_execution_event_stream", MagicMock())
    monkeypatch.setattr(runner, "reap_unlabelled_if_alone", AsyncMock())
    monkeypatch.setattr(
        runner.DockerDeadHostReaper,
        "for_local_engine",
        AsyncMock(return_value=runner.DockerDeadHostReaper(_ENGINE)),
    )
    return queue


async def _registered(queue: InMemoryExecutionRunQueue) -> bool:
    """Whether this process's executor is registered: only a registered one may heartbeat."""
    try:
        await queue.heartbeat(host_labels()[LABEL_HOST_ID])
    except LookupError:
        return False
    return True


async def test_a_differing_declaration_refuses_startup_and_starts_no_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = await _queue_with_a_live_member(monkeypatch)
    monkeypatch.setenv("SYN_EXECUTOR_POOL_PRIORITY", "2")
    reset_settings()
    try:
        with pytest.raises(PoolDefinitionConflict):
            await runner.start_execution_host()
        assert runner._host_task is None
        assert not await _registered(queue)
        assert await queue.heartbeat(_LIVE) is False  # the live member is untouched
    finally:
        await runner.stop_execution_host()
        reset_settings()


async def test_a_matching_declaration_starts_and_stop_leaves_the_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = await _queue_with_a_live_member(monkeypatch)
    monkeypatch.setenv("SYN_EXECUTOR_POOL_PRIORITY", "1")
    reset_settings()
    try:
        await runner.start_execution_host()
        task = runner._host_task
        assert task is not None and not task.done()
        assert await _registered(queue)  # before startup returned
        await runner.stop_execution_host()
        assert task.cancelled()
        assert not await _registered(queue)  # left on shutdown
    finally:
        await runner.stop_execution_host()
        reset_settings()


async def test_the_registered_scope_is_the_local_engines_never_a_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scope the queue fences by is the one ``docker info`` reported (D13)."""
    queue = await _queue_with_a_live_member(monkeypatch)
    monkeypatch.setattr(
        runner.DockerDeadHostReaper,
        "for_local_engine",
        AsyncMock(return_value=runner.DockerDeadHostReaper("engine-from-docker-info")),
    )
    monkeypatch.setenv("SYN_EXECUTOR_POOL_PRIORITY", "1")
    reset_settings()
    try:
        await runner.start_execution_host()
        mine = queue._hosts[host_labels()[LABEL_HOST_ID]].host  # pyright: ignore[reportPrivateUsage]
        assert mine.reap_scope == "engine-from-docker-info"
    finally:
        await runner.stop_execution_host()
        reset_settings()
