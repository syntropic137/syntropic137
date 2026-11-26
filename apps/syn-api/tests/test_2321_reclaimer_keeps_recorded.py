"""A directory the stale-dir reclaimer keeps reaches its execution's stream (#2321).

Drives the consumer - the live clock, `reclaim_on_a_clock` - with a real
`WorkspaceDirReclaimer` over real git directories, the real host-git adapter
and the real domain guard, and hands it the observer the API builds
(`record_reclaim_keeps`) over the real recorder and a stream stored as JSON.
Only docker, the read models and the event store are doubles. The janitor
itself still writes nothing (#1983): the observer is the API's.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from syn_adapters.workspace_backends.remote_refs import GitLsRemote
from syn_adapters.workspace_backends.stale_dirs import (
    ContainerMounts,
    SubprocessHostWorkspaceGit,
    WorkspaceDirListing,
    scan_workspace_dirs,
)
from syn_api.services import workspace_dir_reclaim
from syn_api.services.reclaim_keeps import record_reclaim_keeps
from syn_api.services.workspace_dir_reclaim import (
    PassObserver,
    ReclaimPass,
    WorkspaceDirReclaimer,
    reclaim_on_a_clock,
    start_workspace_reclaim,
    stop_workspace_reclaim,
)
from syn_domain.contexts.orchestration import (
    OwnerExecution,
    RetainedReason,
    RetainedWorkspaceRecorder,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_2321_workspace_retained_recorded import (
    EXECUTION,
    JsonStream,
    started_stream,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

pytestmark = pytest.mark.unit

#: The workspace `started_stream` provisioned for phase `build`.
WORKSPACE = "ws-build"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _dirty_workspace(base: Path, tmp_path: Path) -> Path:
    """``WORKSPACE``, holding one pushed repository with an uncommitted edit."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", str(remote), str(seed))
    (seed / "README.md").write_text("hello\n")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "push", "origin", "HEAD:main")
    ws = base / WORKSPACE
    (ws / "repos").mkdir(parents=True)
    _git(ws / "repos", "clone", str(remote), "app")
    (ws / "repos" / "app" / "README.md").write_text("hello\nonly copy of this line\n")
    return ws


def _reclaimer(
    base: Path,
    tmp_path: Path,
    scan_dirs: Callable[[str], list[WorkspaceDirListing]] = scan_workspace_dirs,
) -> WorkspaceDirReclaimer:
    """Every directory is owned by ``EXECUTION``, completed an hour ago."""

    async def list_containers() -> list[ContainerMounts]:
        return []

    async def workspace_owners(workspace_id: str) -> set[str]:
        return {EXECUTION}

    async def execution_record(execution_id: str) -> OwnerExecution:
        return OwnerExecution(
            execution_id=execution_id,
            status="completed",
            terminal_at=time.time() - 3600,
            repositories=(str(tmp_path / "remote.git"),),
        )

    async def capture_unproven(execution_id: str) -> str | None:
        return None

    return WorkspaceDirReclaimer(
        base_dir=str(base),
        settle_seconds=600.0,
        list_containers=list_containers,
        workspace_owners=workspace_owners,
        execution_record=execution_record,
        capture_unproven=capture_unproven,
        scan_dirs=scan_dirs,
        git=SubprocessHostWorkspaceGit(),
        remotes=GitLsRemote(),
        host_base_dir="/srv/workspaces",
        own_container="api0000000001",
    )


async def _passes(
    reclaimer: WorkspaceDirReclaimer, observer: PassObserver, count: int
) -> list[ReclaimPass]:
    """Run the live clock until ``count`` passes reached ``observer``; return them."""
    seen: list[ReclaimPass] = []
    done = asyncio.Event()

    async def observed(result: ReclaimPass, /) -> None:
        seen.append(result)
        if len(seen) >= count:
            done.set()
        await observer(result)

    task = asyncio.create_task(
        reclaim_on_a_clock(reclaimer, is_live=lambda: True, interval_seconds=0.01, on_pass=observed)
    )
    try:
        await asyncio.wait_for(done.wait(), timeout=30)
        await asyncio.sleep(0.05)  # the last observer call finishes recording
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    return seen


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "workspaces"
    path.mkdir()
    return path


async def test_a_dirty_dir_kept_on_every_pass_is_one_event_on_its_execution(
    base: Path, tmp_path: Path
) -> None:
    ws = _dirty_workspace(base, tmp_path)
    stream = await started_stream()
    observer = record_reclaim_keeps(RetainedWorkspaceRecorder(lambda: stream))

    passes = await _passes(_reclaimer(base, tmp_path), observer, 2)

    first, second = passes[0].retained, passes[1].retained
    assert [(k.workspace_id, k.reason, k.execution_id) for k in first] == [
        (WORKSPACE, RetainedReason.DIRTY, EXECUTION)
    ]
    assert second == first
    # Offered on both passes; the second is a repeat, so the stream says it once.
    assert stream.loads >= 2
    [event] = stream.retained()
    assert (event.execution_id, event.workspace_handle, event.phase_id, event.reason) == (
        EXECUTION,
        WORKSPACE,
        "build",
        RetainedReason.DIRTY,
    )
    assert ws.exists()


async def test_a_keep_made_before_the_owner_was_known_records_nothing(
    base: Path, tmp_path: Path
) -> None:
    """UNREADABLE is unproven work, but a walk that failed names no execution."""
    ws = _dirty_workspace(base, tmp_path)
    stream = await started_stream()
    observer = record_reclaim_keeps(RetainedWorkspaceRecorder(lambda: stream))

    def scan_unreadable(base_dir: str) -> list[WorkspaceDirListing]:
        return [replace(x, unreadable="walk failed") for x in scan_workspace_dirs(base_dir)]

    result, *_ = await _passes(_reclaimer(base, tmp_path, scan_unreadable), observer, 1)

    assert [(k.reason, k.execution_id) for k in result.retained] == [
        (RetainedReason.UNREADABLE, None)
    ]
    assert stream.loads == 0
    assert stream.retained() == []
    assert ws.exists()


def _unopenable() -> JsonStream:
    raise RuntimeError("no event store configured")


async def test_a_recording_failure_leaves_the_clock_running_and_the_dir_kept(
    base: Path, tmp_path: Path
) -> None:
    ws = _dirty_workspace(base, tmp_path)
    observer = record_reclaim_keeps(RetainedWorkspaceRecorder(_unopenable))

    passes = await _passes(_reclaimer(base, tmp_path), observer, 2)

    assert [len(p.retained) for p in passes] == [1, 1]
    assert ws.exists()


async def test_an_observer_that_raises_leaves_the_clock_running_and_the_dir_kept(
    base: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ws = _dirty_workspace(base, tmp_path)

    async def raising(result: ReclaimPass, /) -> None:
        raise RuntimeError("observer broke")

    passes = await _passes(_reclaimer(base, tmp_path), raising, 2)

    assert [p.kept for p in passes] == [(WORKSPACE,), (WORKSPACE,)]
    assert ws.exists()
    assert "observer failed" in caplog.text


async def test_the_started_clock_is_handed_the_callers_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handed: list[object] = []

    async def clock(_reclaimer: object, *, on_pass: object = None, **_kw: object) -> None:
        handed.append(on_pass)

    async def observer(result: ReclaimPass, /) -> None:
        return None

    monkeypatch.setattr(workspace_dir_reclaim, "default_reclaimer", lambda _is_live: None)
    monkeypatch.setattr(workspace_dir_reclaim, "reclaim_on_a_clock", clock)
    monkeypatch.setattr("syn_api.services.disk_pressure.pressure_event", lambda: None)
    try:
        start_workspace_reclaim(lambda: None, observer)
        await asyncio.sleep(0)
    finally:
        await stop_workspace_reclaim()
    assert handed == [observer]
