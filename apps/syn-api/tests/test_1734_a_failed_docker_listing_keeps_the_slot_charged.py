"""A ``docker ps`` that fails is not an empty daemon (ADR-072 D3; #1734).

A failed listing prints nothing on stdout, which is exactly what a daemon with
no matching containers prints. Read as "nothing left", it lets the host's
reap-before-close gate free a slot whose workspace may still be running.

Driven through the real ``ExecutionHost`` drive, the production Docker reaper
and its listing helper, and the guarded in-memory Run Queue. Only the
subprocess boundary and the drain are doubles; the unpushed-work guard is
pinned in test_host_scoped_reap_guards_unpushed_work_first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.execution_host import ExecutionHost
from syn_adapters.execution_runs.memory import InMemoryExecutionRunQueue
from syn_api.services.dead_host_reaper import DockerDeadHostReaper
from syn_domain.contexts.orchestration.ports import ClaimedRun, ExecutorHost
from syn_shared.settings import reset_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_OWNER = ExecutorHost(host_id="a", container_id="c-a", generation="g", epoch=1, reap_scope="s1")


@pytest.fixture(autouse=True)
def _no_guard(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    reset_settings()
    with patch(
        "syn_api.services.dead_host_reaper._guard_orphaned_workspaces",
        new=AsyncMock(return_value=[]),
    ):
        yield
    reset_settings()


def _listing(returncode: int) -> MagicMock:
    """An empty ``docker ps``; a failed one says why on stderr, never on stdout."""
    proc = MagicMock()
    proc.returncode = returncode
    stderr = b"Cannot connect to the Docker daemon" if returncode else b""
    proc.communicate = AsyncMock(return_value=(b"", stderr))
    return proc


async def _claimed() -> tuple[InMemoryExecutionRunQueue, ClaimedRun]:
    queue = InMemoryExecutionRunQueue()
    await queue.register(_OWNER, 1)
    await queue.heartbeat(_OWNER.host_id)
    await queue.reserve("exec-1", 1, is_resume=False)
    await queue.mark_admitted("exec-1")
    claimed = await queue.claim(_OWNER.host_id)
    assert claimed is not None
    return queue, claimed


async def _drive(
    queue: InMemoryExecutionRunQueue, claimed: ClaimedRun, sidecar: int, workspace: int
) -> AsyncMock:
    drainer = MagicMock()
    drainer.run_claimed = AsyncMock(return_value="completed")
    host = ExecutionHost(
        queue,
        _OWNER,
        capacity=1,
        drainer=drainer,
        reaper=DockerDeadHostReaper(),
        interrupter=MagicMock(),
        streams=MagicMock(),
    )
    spawn = AsyncMock(side_effect=[_listing(sidecar), _listing(workspace)])
    with patch("syn_api.services.reconciliation.asyncio.create_subprocess_exec", new=spawn):
        await host._drive(claimed)
    return spawn


@pytest.mark.parametrize(
    ("sidecar", "workspace"),
    [(1, 0), (0, 1), (1, 1)],
    ids=["sidecar-listing-fails", "workspace-listing-fails", "both-fail"],
)
async def test_a_failed_listing_keeps_the_run_charged_until_a_reap_confirms(
    sidecar: int, workspace: int
) -> None:
    queue, claimed = await _claimed()

    spawn = await _drive(queue, claimed, sidecar, workspace)

    # Every selector was asked: one successful listing must not mask another's failure.
    assert spawn.await_count == 2
    counts = await queue.in_use()
    assert (counts.claimed, counts.done) == (1, 0)

    # The same run, once both listings succeed and show nothing, is released.
    await _drive(queue, claimed, 0, 0)
    counts = await queue.in_use()
    assert (counts.claimed, counts.done) == (0, 1)


async def test_a_successful_empty_listing_releases_the_run() -> None:
    queue, claimed = await _claimed()

    await _drive(queue, claimed, 0, 0)

    counts = await queue.in_use()
    assert (counts.claimed, counts.done) == (0, 1)
