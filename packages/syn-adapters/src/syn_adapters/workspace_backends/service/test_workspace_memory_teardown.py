"""Workspace memory is freed only when the container is shown gone (okrs-51p.30, Codex on #2148).

Over-commits Codex reproduced against earlier versions:

- a teardown that failed or was interrupted released the memory while the
  container lived on, so another workspace was admitted beside it;
- a container whose sidecar failed to start was never destroyed (its handle
  was lost with the unfinished tuple assignment) and its memory was released;
- (pass 2) a create that made a container, failed its TMPDIR setup and failed
  to remove it raised as if nothing existed, and the memory was released;
- (pass 2) a cancelled create left its ``docker run`` going: a reap could see
  nothing, settle, and then the container appeared;
- (pass 2) a leak was settled only by the Run Queue's reap, so with the queue
  off it was lost until restart.

The memory reconciler is the one path that settles a leak. None of these
tests wires a reaper: it settles with the Run Queue off. Each case asserts
both halves: what happened to the container, and whether the ledger still
charges for it.
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
from syn_adapters.workspace_backends.service.memory_reconciler import WorkspaceMemoryReconciler
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


class _Listing:
    """``docker ps`` over the memory backend: every workspace with a container."""

    def __init__(self, isolation: MemoryIsolationAdapter) -> None:
        self._isolation = isolation

    async def listed(self) -> frozenset[str]:
        return frozenset(s.config.workspace_id for s in self._isolation._instances.values())


def _reconciler(
    ledger: WorkspaceMemoryLedger, isolation: MemoryIsolationAdapter
) -> WorkspaceMemoryReconciler:
    return WorkspaceMemoryReconciler(ledger, _Listing(isolation))


async def _drain() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


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

    reconciler = _reconciler(ledger, isolation)
    assert await reconciler.run_once() == 0, "listed, so not settled"
    isolation._instances.clear()  # removed at last, by anyone
    assert await reconciler.run_once() == 4096
    assert ledger.reserved_mb == 0


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
    assert await _reconciler(ledger, isolation).run_once() == 0, "the container is listed"


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


async def test_a_cancelled_create_is_seen_through_and_settled_only_after() -> None:
    """Pass 2 P1 3: the create outlives the cancel, then its container appears."""
    ledger = WorkspaceMemoryLedger(4096)
    service, isolation = _service(ledger)
    reconciler = _reconciler(ledger, isolation)
    real_create = isolation.create
    creating = asyncio.Event()
    docker_run_finishes = asyncio.Event()

    async def slow_create(config: object) -> IsolationHandle:
        creating.set()
        await docker_run_finishes.wait()
        return await real_create(config)  # type: ignore[arg-type]  # IsolationConfig, typed loosely by patch

    with patch.object(isolation, "create", slow_create):
        task = asyncio.create_task(_use(service))
        await creating.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert isolation._instances == {}, "nothing listed yet"
        assert await reconciler.run_once() == 0, "a create in flight may still make one"
        assert ledger.reserved_mb == 4096

        docker_run_finishes.set()
        await _drain()

    assert isolation._instances == {}, "what the abandoned create made was destroyed"
    assert await reconciler.run_once() == 4096
    assert ledger.reserved_mb == 0


async def test_a_container_the_listing_missed_mid_create_is_not_settled() -> None:
    """The create ends DURING the listing, and its container survives: only the
    in-flight read taken before listing keeps the memory charged."""
    ledger = WorkspaceMemoryLedger(4096)
    service, isolation = _service(ledger)
    real_create = isolation.create
    creating = asyncio.Event()
    docker_run_finishes = asyncio.Event()

    async def slow_create(config: object) -> IsolationHandle:
        creating.set()
        await docker_run_finishes.wait()
        return await real_create(config)  # type: ignore[arg-type]  # IsolationConfig, typed loosely by patch

    async def refuse(handle: IsolationHandle) -> None:
        raise _Boom("docker rm timed out")

    class _StaleListing:
        """Reads the daemon, THEN the create lands and its removal fails."""

        async def listed(self) -> frozenset[str]:
            snapshot = await _Listing(isolation).listed()
            docker_run_finishes.set()
            await _drain()
            return snapshot

    with patch.object(isolation, "create", slow_create), patch.object(isolation, "destroy", refuse):
        task = asyncio.create_task(_use(service))
        await creating.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        freed = await WorkspaceMemoryReconciler(ledger, _StaleListing()).run_once()

    assert len(isolation._instances) == 1, "the container lives"
    assert freed == 0
    assert ledger.reserved_mb == 4096


async def test_a_create_that_made_a_container_and_raised_keeps_the_memory_charged() -> None:
    """Pass 2 P1 2, Codex's repro: create OK, TMPDIR setup fails, its removal
    fails and is swallowed, and the adapter raises WorkspaceProvisionError."""
    ledger = WorkspaceMemoryLedger(4096)
    service, isolation = _service(ledger)
    reconciler = _reconciler(ledger, isolation)
    real_create = isolation.create

    async def tmpdir_fails(config: object) -> IsolationHandle:
        await real_create(config)  # type: ignore[arg-type]  # IsolationConfig, typed loosely by patch
        raise _Boom("could not create TMPDIR /workspace/.tmp")

    with patch.object(isolation, "create", tmpdir_fails), pytest.raises(_Boom):
        await _use(service)

    assert len(isolation._instances) == 1, "the container no handle names"
    assert ledger.reserved_mb == 4096
    assert await reconciler.run_once() == 0, "listed, so not settled"
    isolation._instances.clear()
    assert await reconciler.run_once() == 4096


async def test_a_create_that_raised_and_made_nothing_is_settled_by_the_reconciler() -> None:
    """The control: once a listing shows nothing, the memory comes back."""
    ledger = WorkspaceMemoryLedger(4096)
    service, isolation = _service(ledger)

    async def refuse(*_: object) -> None:
        raise _Boom("image pull failed")

    with patch.object(isolation, "create", refuse), pytest.raises(_Boom):
        await _use(service)

    assert ledger.reserved_mb == 4096, "not trusted until listed"
    assert await _reconciler(ledger, isolation).run_once() == 4096
    assert ledger.reserved_mb == 0


async def test_a_listing_that_fails_settles_nothing() -> None:
    ledger = WorkspaceMemoryLedger(4096)
    (await ledger.reserve(4096, workspace_id="ws")).leak("exec-1", reason="x")

    class _Down:
        async def listed(self) -> frozenset[str]:
            raise RuntimeError("Cannot connect to the Docker daemon")

    assert await WorkspaceMemoryReconciler(ledger, _Down()).run_once() is None, "unknown, not 0 MB"
    assert ledger.reserved_mb == 4096


async def test_nothing_leaked_lists_nothing() -> None:
    ledger = WorkspaceMemoryLedger(4096)

    class _MustNotList:
        async def listed(self) -> frozenset[str]:
            raise AssertionError("listed with nothing to settle")

    assert await WorkspaceMemoryReconciler(ledger, _MustNotList()).run_once() == 0


async def test_a_clean_teardown_frees_the_memory() -> None:
    ledger = WorkspaceMemoryLedger(4096)
    service, isolation = _service(ledger)

    await _use(service)

    assert isolation._instances == {}
    assert ledger.reserved_mb == 0
