"""A phase's memory request reaches its container limit, is recorded, and is held to the ceiling (okrs-51p.30)."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

import pytest

from syn_adapters.workspace_backends.memory.memory_adapter import MemoryIsolationAdapter
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_adapters.workspace_backends.service.memory_ledger import WorkspaceMemoryLedger
from syn_adapters.workspace_backends.service.workspace_service import WorkspaceServiceConfig
from syn_domain.contexts.orchestration import WorkspaceMemoryOverCapError, WorkspaceResourceRequest
from syn_shared.settings.workspace import WorkspaceSettings

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _test_environment():
    with patch.dict(os.environ, {"APP_ENVIRONMENT": "test"}):
        yield


def _service(
    *, max_mb: int = 16384, ledger: WorkspaceMemoryLedger | None = None
) -> WorkspaceService:
    return WorkspaceService.create(
        backend=WorkspaceBackend.MEMORY,
        config=WorkspaceServiceConfig(memory_limit_mb=4096, memory_max_mb=max_mb),
        memory_ledger=ledger,
    )


def _container_memory(service: WorkspaceService, isolation_id: str) -> int:
    isolation = service._isolation
    assert isinstance(isolation, MemoryIsolationAdapter)
    return isolation._instances[isolation_id].config.security_policy.memory_limit_mb


def _recorded_memory(workspace: object) -> int:
    events = list(workspace.aggregate._uncommitted_events)  # type: ignore[attr-defined]
    created = next(e.event for e in events if e.event.event_type == "WorkspaceCreated")
    return created.security_settings["memory_limit_mb"]


async def test_the_request_is_the_container_limit_and_is_recorded_on_workspace_created() -> None:
    service = _service()

    async with service.create_workspace(
        execution_id="exec-1",
        phase_id="build",
        with_sidecar=False,
        resources=WorkspaceResourceRequest(memory_mb=12288),
    ) as workspace:
        assert _container_memory(service, workspace.isolation_handle.isolation_id) == 12288
        assert _recorded_memory(workspace) == 12288


async def test_no_request_is_the_configured_default_and_is_recorded_as_such() -> None:
    """Before this, WorkspaceCreated recorded SecurityPolicy's 4096 whatever the setting."""
    service = WorkspaceService.create(
        backend=WorkspaceBackend.MEMORY,
        config=WorkspaceServiceConfig(memory_limit_mb=3072, memory_max_mb=3072),
    )

    async with service.create_workspace(execution_id="exec-1", with_sidecar=False) as workspace:
        assert _container_memory(service, workspace.isolation_handle.isolation_id) == 3072
        assert _recorded_memory(workspace) == 3072


async def test_a_request_above_the_ceiling_is_refused_before_any_container() -> None:
    service = _service(max_mb=8192)
    isolation = service._isolation
    assert isinstance(isolation, MemoryIsolationAdapter)

    with pytest.raises(WorkspaceMemoryOverCapError, match="build"):
        async with service.create_workspace(
            execution_id="exec-1",
            phase_id="build",
            with_sidecar=False,
            resources=WorkspaceResourceRequest(memory_mb=12288),
        ):
            pytest.fail("a refused workspace must never be entered")

    assert isolation._instances == {}


async def test_the_workspace_holds_its_memory_until_teardown() -> None:
    ledger = WorkspaceMemoryLedger(16384)
    service = _service(ledger=ledger)

    async with service.create_workspace(
        execution_id="exec-1",
        with_sidecar=False,
        resources=WorkspaceResourceRequest(memory_mb=12288),
    ):
        assert ledger.reserved_mb == 12288

    assert ledger.reserved_mb == 0


async def test_a_second_large_workspace_waits_for_the_first() -> None:
    """The over-commit this guards: two 12 GB builds admitted as two runs on a 16 GB budget."""
    ledger = WorkspaceMemoryLedger(16384)
    service = _service(ledger=ledger)
    big = WorkspaceResourceRequest(memory_mb=12288)
    second_entered = asyncio.Event()

    async def second() -> None:
        async with service.create_workspace(
            execution_id="exec-2", with_sidecar=False, resources=big
        ):
            second_entered.set()

    async with service.create_workspace(execution_id="exec-1", with_sidecar=False, resources=big):
        task = asyncio.create_task(second())
        for _ in range(10):
            await asyncio.sleep(0)
        assert not second_entered.is_set()
        assert ledger.waiting == 1

    await asyncio.wait_for(task, timeout=1)
    assert second_entered.is_set()
    assert ledger.reserved_mb == 0


def test_the_ceiling_comes_from_settings_and_unset_means_the_default() -> None:
    with patch.dict(os.environ, {}, clear=True):
        unset = WorkspaceServiceConfig.from_settings(WorkspaceSettings(_env_file=None))
        assert unset.memory_max_mb == unset.memory_limit_mb == 4096
    with patch.dict(os.environ, {"SYN_WORKSPACE_MEMORY_MAX_MB": "16384"}, clear=True):
        raised = WorkspaceServiceConfig.from_settings(WorkspaceSettings(_env_file=None))
        assert raised.memory_max_mb == 16384


def test_a_ceiling_below_the_default_is_refused_at_startup() -> None:
    env = {"SYN_WORKSPACE_MEMORY_LIMIT_MB": "8192", "SYN_WORKSPACE_MEMORY_MAX_MB": "4096"}
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValueError, match="must cover"):
        WorkspaceSettings(_env_file=None)
