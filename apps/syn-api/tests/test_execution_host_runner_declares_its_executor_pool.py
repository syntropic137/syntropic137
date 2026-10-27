"""The ExecutionHost registers into the Executor Pool its settings name (ADR-072 D13).

Tested at the consumer: the ``ExecutorHost`` the runner hands the ExecutionHost,
which is what ``register`` writes, not the settings object alone.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_api.services import execution_host_runner as runner
from syn_domain.contexts.orchestration.ports import (
    DEFAULT_EXECUTOR_POOL,
    Capability,
    ExecutorHost,
    ExecutorPool,
    IsolationLevel,
)
from syn_shared.settings import reset_settings

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


class _Reaper:
    """The backend as the runner reads it; ``docker info`` is not called in a unit test."""

    def __init__(
        self, provider: str = "docker", isolation: IsolationLevel = IsolationLevel.CONTAINER
    ) -> None:
        self._provider, self._isolation = provider, isolation

    def scope(self) -> str:
        return "engine-under-test"

    def provider(self) -> str:
        return self._provider

    def isolation(self) -> IsolationLevel:
        return self._isolation

    async def reap(self, executor_id: str, execution_id: str) -> bool:
        return True


async def _started_host(
    monkeypatch: pytest.MonkeyPatch, reaper: _Reaper | None = None
) -> ExecutorHost:
    executor = MagicMock()
    executor.join = AsyncMock()
    executor.leave = AsyncMock()
    executor.run_until_drained = AsyncMock()
    built = MagicMock(return_value=executor)
    monkeypatch.setattr(runner, "get_execution_run_queue", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(runner, "get_execution_processor", AsyncMock())
    monkeypatch.setattr(runner, "get_workflow_execution_repository", MagicMock())
    monkeypatch.setattr(runner, "get_execution_event_stream", MagicMock())
    monkeypatch.setattr(runner, "ExecutionHost", built)
    monkeypatch.setattr(runner, "reap_unlabelled_if_alone", AsyncMock())
    monkeypatch.setattr(runner, "DockerDeadHostReaper", lambda: reaper or _Reaper())
    reset_settings()
    try:
        await runner.start_execution_host()
    finally:
        await runner.stop_execution_host()
        reset_settings()
    (_, host), _ = built.call_args
    assert isinstance(host, ExecutorHost)
    return host


async def test_the_host_declares_the_pool_its_settings_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SYN_EXECUTOR_POOL_ID", "vps-local")
    monkeypatch.setenv("SYN_EXECUTOR_POOL_PRIORITY", "2")
    monkeypatch.setenv("SYN_EXECUTOR_POOL_REGION", "eu-central")
    monkeypatch.setenv("SYN_EXECUTOR_POOL_CAPABILITIES", '["nested_docker"]')
    monkeypatch.setenv("SYN_EXECUTOR_POOL_OVERFLOW_DELAY_S", "45")
    monkeypatch.setenv("SYN_EXECUTOR_POOL_OVERFLOW_BUDGET_USD_PER_DAY", "30")

    host = await _started_host(monkeypatch)

    assert host.pool == ExecutorPool(
        pool_id="vps-local",
        priority=2,
        provider="docker",
        region="eu-central",
        isolation=IsolationLevel.CONTAINER,
        capabilities=frozenset({Capability.NESTED_DOCKER}),
        overflow_delay=timedelta(seconds=45),
        overflow_budget_usd_per_day=30,
    )


async def test_unset_pool_settings_join_the_seeded_default_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # .env.example writes unset values as empty strings.
    monkeypatch.setenv("SYN_EXECUTOR_POOL_REGION", "")
    monkeypatch.setenv("SYN_EXECUTOR_POOL_CAPABILITIES", "")
    host = await _started_host(monkeypatch)
    assert host.pool == DEFAULT_EXECUTOR_POOL


async def test_an_unknown_capability_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYN_EXECUTOR_POOL_CAPABILITIES", '["gpu"]')
    with pytest.raises(ValueError, match="gpu"):
        await _started_host(monkeypatch)


async def test_the_host_records_its_reapers_scope_and_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scope, provider and isolation are read from the backend (D13), never from
    # settings: a provider and level no setting could produce prove the source.
    host = await _started_host(monkeypatch, _Reaper("kata", IsolationLevel.MICROVM))
    assert host.reap_scope == "engine-under-test"
    assert (host.pool.provider, host.pool.isolation) == ("kata", IsolationLevel.MICROVM)


async def test_e2b_with_the_run_queue_refuses_to_start_until_its_executor_is_wired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The pool would declare host credentials and a Docker reaper for E2B
    # workspaces, so it could claim agent runs a NoCredentials backend cannot run.
    monkeypatch.setenv("SYN_E2B_ENABLED", "true")
    monkeypatch.setenv("SYN_E2B_API_KEY", "e2b-invented-for-test")
    monkeypatch.setenv("SYN_E2B_TEMPLATE", "syn-template-under-test")
    with pytest.raises(runner.UnwiredExecutorBackend, match="E2B Executor is not wired"):
        await _started_host(monkeypatch)
