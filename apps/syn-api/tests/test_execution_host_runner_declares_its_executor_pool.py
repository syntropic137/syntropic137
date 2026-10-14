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


async def _started_host(monkeypatch: pytest.MonkeyPatch) -> ExecutorHost:
    executor = MagicMock()
    executor.run_until_drained = AsyncMock()
    built = MagicMock(return_value=executor)
    monkeypatch.setattr(runner, "get_execution_run_queue", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(runner, "get_execution_processor", AsyncMock())
    monkeypatch.setattr(runner, "get_workflow_execution_repository", MagicMock())
    monkeypatch.setattr(runner, "get_execution_event_stream", MagicMock())
    monkeypatch.setattr(runner, "ExecutionHost", built)
    monkeypatch.setattr(runner, "reap_unlabelled_if_alone", AsyncMock())
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

    host = await _started_host(monkeypatch)

    assert host.pool == ExecutorPool(
        pool_id="vps-local",
        priority=2,
        provider="docker",
        region="eu-central",
        isolation=IsolationLevel.CONTAINER,
        capabilities=frozenset({Capability.NESTED_DOCKER}),
        overflow_delay=timedelta(seconds=45),
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
