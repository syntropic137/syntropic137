"""PC-130: workspace directories whose container is gone are reclaimed, guarded.

Every test drives `WorkspaceDirReclaimer.run_once` - the consumer - over real
directories holding real git repositories with a real (bare) remote, through
the real host-git adapter and the real domain guard. Only docker, the
execution projection and MinIO are doubles.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from typing import TYPE_CHECKING

import pytest

from syn_adapters.workspace_backends.orphaned import ShutilWorkspaceDirRemover, parse_inspect
from syn_adapters.workspace_backends.stale_dirs import (
    SubprocessHostWorkspaceGit,
    WorkspaceContainer,
    scan_workspace_dirs,
)
from syn_api.services.workspace_dir_reclaim import WorkspaceDirReclaimer, reclaim_on_a_clock

if TYPE_CHECKING:
    from pathlib import Path

    from syn_domain.contexts.orchestration import StaleWorkspaceDir

pytestmark = pytest.mark.unit

_GRACE = 6 * 3600.0


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _workspace(base: Path, workspace_id: str, tmp_path: Path) -> Path:
    """A workspace dir holding one repo cloned from a bare remote, fully pushed."""
    remote = tmp_path / f"{workspace_id}-remote.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    seed = tmp_path / f"{workspace_id}-seed"
    _git(tmp_path, "clone", str(remote), str(seed))
    (seed / "README.md").write_text("hello\n")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "push", "origin", "HEAD:main")
    ws = base / workspace_id
    (ws / "repos").mkdir(parents=True)
    _git(ws / "repos", "clone", str(remote), "app")
    return ws


class _Archive:
    def __init__(self, *, fail: bool = False) -> None:
        self.saved: list[tuple[str | None, bytes]] = []
        self._fail = fail

    async def save(self, stale: StaleWorkspaceDir, repo: str, patch: bytes) -> str:
        if self._fail:
            raise OSError("minio down")
        self.saved.append((stale.execution_id, patch))
        return f"s3://artifacts/{stale.execution_id}/reclaimed-{stale.workspace_id}.md"


def _reclaimer(
    base: Path,
    *,
    containers: list[WorkspaceContainer] | None = None,
    running: set[str] | None = None,
    archive: _Archive | None = None,
    hours_later: float = 7.0,
) -> WorkspaceDirReclaimer:
    async def list_containers() -> list[WorkspaceContainer]:
        return containers or []

    async def running_ids() -> set[str]:
        return running or set()

    return WorkspaceDirReclaimer(
        base_dir=str(base),
        grace_seconds=_GRACE,
        list_containers=list_containers,
        running_execution_ids=running_ids,
        scan_dirs=scan_workspace_dirs,
        git=SubprocessHostWorkspaceGit(),
        archive=archive or _Archive(),
        remover=ShutilWorkspaceDirRemover(),
        clock=lambda: time.time() + hours_later * 3600,
    )


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "workspaces"
    path.mkdir()
    return path


async def test_clean_pushed_stale_dir_is_reclaimed_and_logged_with_size(
    base: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ws = _workspace(base, "ws-clean", tmp_path)
    caplog.set_level(logging.INFO)
    result = await _reclaimer(base).run_once()
    assert result.reclaimed == ("ws-clean",)
    assert result.reclaimed_bytes > 0
    assert not ws.exists()
    assert f"WorkspaceReclaimed workspace_id=ws-clean host_dir={ws} size_bytes=" in caplog.text


async def test_unpushed_commit_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-unpushed", tmp_path)
    app = ws / "repos" / "app"
    _git(app, "checkout", "-b", "agent-work")
    (app / "feature.py").write_text("x = 1\n")
    _git(app, "add", "feature.py")
    _git(app, "commit", "-m", "never pushed")
    archive = _Archive()
    result = await _reclaimer(base, archive=archive).run_once()
    assert result.kept == ("ws-unpushed",)
    assert ws.exists()
    assert archive.saved == []


async def test_unpushed_commit_on_a_detached_head_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-detached", tmp_path)
    app = ws / "repos" / "app"
    _git(app, "checkout", "--detach")
    (app / "f.py").write_text("y = 2\n")
    _git(app, "add", "f.py")
    _git(app, "commit", "-m", "detached")
    result = await _reclaimer(base).run_once()
    assert result.kept == ("ws-detached",)
    assert ws.exists()


async def test_dirty_tree_is_saved_as_a_patch_then_deleted(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-dirty", tmp_path)
    app = ws / "repos" / "app"
    (app / "README.md").write_text("hello\nedited by the agent\n")
    (app / "new_untracked.py").write_text("print('only copy')\n")
    archive = _Archive()
    containers = [WorkspaceContainer(workspace_id="ws-dirty", execution_id="exec-9", running=False)]
    result = await _reclaimer(base, containers=containers, archive=archive).run_once()
    assert result.reclaimed == ("ws-dirty",)
    assert not ws.exists()
    [(execution_id, patch)] = archive.saved
    assert execution_id == "exec-9"
    assert b"+edited by the agent" in patch
    assert b"+print('only copy')" in patch


async def test_failed_patch_save_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-dirty-nosave", tmp_path)
    (ws / "repos" / "app" / "README.md").write_text("changed\n")
    result = await _reclaimer(base, archive=_Archive(fail=True)).run_once()
    assert result.kept == ("ws-dirty-nosave",)
    assert (ws / "repos" / "app" / "README.md").read_text() == "changed\n"


async def test_live_container_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-live", tmp_path)
    containers = [WorkspaceContainer(workspace_id="ws-live", execution_id="exec-1", running=True)]
    result = await _reclaimer(base, containers=containers).run_once()
    assert result.reclaimed == ()
    assert ws.exists()


async def test_running_execution_keeps_the_dir_even_with_its_container_stopped(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-owned", tmp_path)
    containers = [
        WorkspaceContainer(workspace_id="ws-owned", execution_id="exec-run", running=False)
    ]
    result = await _reclaimer(base, containers=containers, running={"exec-run"}).run_once()
    assert result.reclaimed == ()
    assert ws.exists()


async def test_within_grace_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-recent", tmp_path)
    result = await _reclaimer(base, hours_later=5.0).run_once()
    assert result.reclaimed == ()
    assert ws.exists()


async def test_unreadable_docker_skips_the_whole_pass(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-unknown", tmp_path)
    reclaimer = _reclaimer(base)

    async def docker_down() -> list[WorkspaceContainer]:
        raise RuntimeError("docker unreachable")

    reclaimer.list_containers = docker_down
    result = await reclaimer.run_once()
    assert result.skipped is not None
    assert ws.exists()


async def test_repo_config_naming_a_command_is_never_run_and_keeps_the_dir(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-hostile", tmp_path)
    app = ws / "repos" / "app"
    marker = tmp_path / "pwned"
    _git(app, "config", "core.fsmonitor", f"touch {marker}; false")
    (app / "README.md").write_text("changed\n")
    result = await _reclaimer(base).run_once()
    assert result.kept == ("ws-hostile",)
    assert ws.exists()
    assert not marker.exists()


async def test_no_pass_runs_while_catching_up(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-replay", tmp_path)
    task = asyncio.create_task(
        reclaim_on_a_clock(_reclaimer(base), is_live=lambda: False, interval_seconds=0.01)
    )
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ws.exists()


def test_inspect_reads_whether_the_container_is_running() -> None:
    raw = (
        '[{"State": {"Running": false, "OOMKilled": true},'
        ' "Config": {"Labels": {"syn.execution_id": "e"}},'
        ' "Mounts": [{"Destination": "/workspace", "Source": "/w/ws-1"}]}]'
    )
    inspected = parse_inspect(raw)
    assert inspected is not None
    assert inspected.running is False
    assert parse_inspect(raw.replace('"Running": false', '"Running": true')).running is True  # type: ignore[union-attr]
