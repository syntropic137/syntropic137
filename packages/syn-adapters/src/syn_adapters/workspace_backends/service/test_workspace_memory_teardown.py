"""Workspace memory is freed only when the container is shown gone (okrs-51p.30, Codex on #2148).

Two over-commits Codex reproduced against the first version:

- a teardown that failed or was interrupted released the memory while the
  container lived on, so another workspace was admitted beside it;
- a container whose sidecar failed to start was never destroyed (its handle
  was lost with the unfinished tuple assignment) and its memory was released.

Each case asserts both halves: what happened to the container, and whether
the ledger still charges for it.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from syn_adapters.workspace_backends.memory.memory_adapter import MemoryIsolationAdapter
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_adapters.workspace_backends.service.memory_ledger import WorkspaceMemoryLedger
from syn_adapters.workspace_backends.service.workspace_service import WorkspaceServiceConfig
from syn_domain.contexts.orchestration import WorkspaceResourceRequest

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )

pytestmark = pytest.mark.unit

_BIG = WorkspaceResourceRequest(memory_mb=4096)


@pytest.fixture(autouse=True)
def _test_environment():
    with patch.dict(os.environ, {"APP_ENVIRONMENT": "test"}):
        yield


def _service(ledger: WorkspaceMemoryLedger) -> tuple[WorkspaceService, MemoryIsolationAdapter]:
    service = WorkspaceService.create(
        backend=WorkspaceBackend.MEMORY,
        config=WorkspaceServiceConfig(memory_limit_mb=4096, memory_max_mb=4096),
        memory_ledger=ledger,
    )
    isolation = service._isolation
    assert isinstance(isolation, MemoryIsolationAdapter)
    return service, isolation


class _Boom(Exception):
    pass


async def _use(service: WorkspaceService, *, with_sidecar: bool = False) -> None:
    async with service.create_workspace(
        execution_id="exec-1", with_sidecar=with_sidecar, resources=_BIG
    ):
        pass


async def test_a_failed_destroy_keeps_the_memory_charged() -> None:
    ledger = WorkspaceMemoryLedger(4096)
    service, isolation = _service(ledger)

    async def refuse(handle: IsolationHandle) -> None:
        raise _Boom("docker rm timed out")

    with patch.object(isolation, "destroy", refuse):
        await _use(service)

    assert len(isolation._instances) == 1, "the container is still there"
    assert ledger.reserved_mb == 4096, "so its memory must still be charged"
    assert ledger.leaked_mb == 4096


async def test_a_second_workspace_waits_behind_a_container_that_would_not_die() -> None:
    """Codex's reproduction: 1 live container, 0 MB reserved, another admitted."""
    ledger = WorkspaceMemoryLedger(4096)
    service, isolation = _service(ledger)

    async def refuse(handle: IsolationHandle) -> None:
        raise _Boom("docker rm timed out")

    with patch.object(isolation, "destroy", refuse):
        await _use(service)
    second = asyncio.create_task(_use(service))
    for _ in range(10):
        await asyncio.sleep(0)

    assert not second.done(), "admitted beside a container still holding the memory"
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second


async def test_an_interrupted_teardown_keeps_the_memory_charged() -> None:
    ledger = WorkspaceMemoryLedger(4096)
    service, isolation = _service(ledger)
    destroying = asyncio.Event()

    async def hang(handle: IsolationHandle) -> None:
        destroying.set()
        await asyncio.Event().wait()

    with patch.object(isolation, "destroy", hang):
        task = asyncio.create_task(_use(service))
        await destroying.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert ledger.reserved_mb == 4096


async def test_a_sidecar_that_will_not_start_does_not_leak_its_container() -> None:
    """Codex's reproduction: 2 live containers against a 1-container pool."""
    ledger = WorkspaceMemoryLedger(4096)
    service, isolation = _service(ledger)

    async def refuse(*_: object) -> None:
        raise _Boom("envoy unreachable")

    with patch.object(service._sidecar, "start", refuse):
        for _ in range(2):
            with pytest.raises(_Boom):
                await _use(service, with_sidecar=True)

    assert isolation._instances == {}, "the container behind the failed sidecar was left running"
    assert ledger.reserved_mb == 0, "destroyed, so its memory is free"


async def test_a_failed_sidecar_and_a_failed_destroy_keep_the_memory_charged() -> None:
    ledger = WorkspaceMemoryLedger(4096)
    service, isolation = _service(ledger)

    async def refuse(*_: object) -> None:
        raise _Boom("nope")

    with (
        patch.object(service._sidecar, "start", refuse),
        patch.object(isolation, "destroy", refuse),
        pytest.raises(_Boom),
    ):
        await _use(service, with_sidecar=True)

    assert len(isolation._instances) == 1
    assert ledger.reserved_mb == 4096


async def test_a_cancel_during_create_keeps_the_memory_charged() -> None:
    """A container may exist that no handle names; it cannot be shown free."""
    ledger = WorkspaceMemoryLedger(4096)
    service, isolation = _service(ledger)
    creating = asyncio.Event()

    async def slow_create(*_: object) -> None:
        creating.set()
        await asyncio.Event().wait()

    with patch.object(isolation, "create", slow_create):
        task = asyncio.create_task(_use(service))
        await creating.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert ledger.reserved_mb == 4096


async def test_a_create_that_raises_frees_the_memory() -> None:
    """The control: the backend reports nothing was created, so nothing is charged."""
    ledger = WorkspaceMemoryLedger(4096)
    service, isolation = _service(ledger)

    async def refuse(*_: object) -> None:
        raise _Boom("image pull failed")

    with patch.object(isolation, "create", refuse), pytest.raises(_Boom):
        await _use(service)

    assert ledger.reserved_mb == 0


async def test_a_clean_teardown_frees_the_memory() -> None:
    ledger = WorkspaceMemoryLedger(4096)
    service, isolation = _service(ledger)

    await _use(service)

    assert isolation._instances == {}
    assert ledger.reserved_mb == 0
