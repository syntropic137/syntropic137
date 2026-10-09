"""#1805: a running workspace over its disk cap is saved, then stopped.

Every test drives `WorkspaceDiskCapEnforcer.run_once` over real directories
holding real git repositories with a real (bare) remote, measured by the real
`scan_workspace_dirs` and read by the real host-git adapter. Only docker
(the container list, `docker pause`/`unpause`/`kill`) and MinIO are doubles.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
from typing import TYPE_CHECKING

import pytest

from syn_adapters.workspace_backends.stale_dirs import (
    SubprocessHostWorkspaceGit,
    WorkspaceContainer,
    scan_workspace_dirs,
)
from syn_api.services import workspace_disk_cap
from syn_api.services.workspace_disk_cap import WorkspaceDiskCapEnforcer

if TYPE_CHECKING:
    from pathlib import Path

    from syn_domain.contexts.orchestration import StaleWorkspaceDir

pytestmark = pytest.mark.unit

_LIMIT = 512 * 1024


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


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


def _grow(ws: Path, size: int = 2 * _LIMIT) -> None:
    (ws / "repos" / "app" / "build.bin").write_bytes(b"\0" * size)


class _Docker:
    """The container list, freeze, thaw and kill, recording into a shared log."""

    def __init__(
        self, log: list[str], running: dict[str, str], *, freeze_fails: bool = False
    ) -> None:
        self.log = log
        self.running = running
        self.frozen: set[str] = set()
        self._freeze_fails = freeze_fails

    async def list_containers(self) -> list[WorkspaceContainer]:
        return [WorkspaceContainer(ws, ex, running=True) for ws, ex in self.running.items()]

    async def freeze(self, workspace_id: str) -> None:
        if self._freeze_fails:
            raise RuntimeError("docker pause exited 1")
        self.log.append(f"freeze {workspace_id}")
        self.frozen.add(workspace_id)

    async def thaw(self, workspace_id: str) -> None:
        self.log.append(f"thaw {workspace_id}")
        self.frozen.discard(workspace_id)

    async def stop(self, workspace_id: str) -> None:
        self.log.append(f"stop {workspace_id}")


class _Archive:
    def __init__(self, log: list[str], *, fail_on: str | None = None) -> None:
        self.log = log
        self.patches: dict[str, bytes] = {}
        self.files: list[bytes] = []
        self._fail_on = fail_on

    async def save(self, stale: StaleWorkspaceDir, repo: str, patch: bytes) -> str:
        kind = "bundle" if repo.endswith(".bundle") else "patch"
        if self._fail_on == kind:
            raise OSError("minio down")
        self.log.append(f"save {kind} {stale.workspace_id} {stale.execution_id}")
        self.patches[repo] = patch
        return f"s3://artifacts/{stale.execution_id}/{kind}"

    async def save_files(self, stale: StaleWorkspaceDir, tarball: bytes) -> str:
        if self._fail_on == "files":
            raise OSError("minio down")
        self.log.append(f"save files {stale.workspace_id} {stale.execution_id}")
        self.files.append(tarball)
        return f"s3://artifacts/{stale.execution_id}/files"


def _enforcer(base: Path, docker: _Docker, archive: _Archive) -> WorkspaceDiskCapEnforcer:
    git = SubprocessHostWorkspaceGit()
    return WorkspaceDiskCapEnforcer(
        base_dir=str(base),
        limit_bytes=_LIMIT,
        list_containers=docker.list_containers,
        scan_dirs=scan_workspace_dirs,
        git=git,
        bundler=git,
        archive=archive,
        freeze_container=docker.freeze,
        thaw_container=docker.thaw,
        stop_container=docker.stop,
    )


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "workspaces"
    path.mkdir()
    return path


def _authored_work(ws: Path) -> None:
    """An unpushed commit, a dirty tracked file, an untracked file and a deliverable."""
    app = ws / "repos" / "app"
    (app / "feature.py").write_text("def f() -> int:\n    return 1\n")
    _git(app, "add", "feature.py")
    _git(app, "commit", "-m", "unpushed feature")
    (app / "README.md").write_text("hello, edited\n")
    (app / "notes.txt").write_text("untracked\n")
    (ws / "artifacts" / "output").mkdir(parents=True)
    (ws / "artifacts" / "output" / "deliverable.md").write_text("# done\n")


async def test_below_cap_is_untouched_then_over_cap_is_saved_before_it_is_stopped(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-big", tmp_path)
    _authored_work(ws)
    log: list[str] = []
    docker = _Docker(log, {"ws-big": "exec-big"})
    archive = _Archive(log)
    enforcer = _enforcer(base, docker, archive)

    first = await enforcer.run_once()
    assert first.stopped == () and log == []

    _grow(ws)
    second = await enforcer.run_once()

    assert second.stopped == ("ws-big",)
    assert log[0] == "freeze ws-big"
    assert log[-1] == "stop ws-big"
    assert sorted(log[1:-1]) == [
        "save bundle ws-big exec-big",
        "save files ws-big exec-big",
        "save patch ws-big exec-big",
    ]
    assert ws.exists()  # Stopping is all this does; the directory is the teardown's.

    # The bundle really holds the unpushed commit: restore it onto a fresh
    # clone of the remote, which is all an operator has once the dir is gone.
    bundle = next(v for k, v in archive.patches.items() if k.endswith(".bundle"))
    (tmp_path / "unpushed.bundle").write_bytes(bundle)
    _git(tmp_path, "clone", str(tmp_path / "ws-big-remote.git"), "restored")
    _git(tmp_path / "restored", "fetch", str(tmp_path / "unpushed.bundle"), "refs/*:refs/saved/*")
    assert "unpushed feature" in _git(tmp_path / "restored", "log", "--all", "--format=%s")

    patch = next(v for k, v in archive.patches.items() if not k.endswith(".bundle"))
    assert b"hello, edited" in patch
    assert b"notes.txt" in patch
    with tarfile.open(fileobj=io.BytesIO(archive.files[0]), mode="r:gz") as tar:
        assert "artifacts/output/deliverable.md" in tar.getnames()


@pytest.mark.parametrize("fail_on", ["bundle", "patch", "files"])
async def test_a_failed_save_is_reported_and_the_run_is_not_stopped(
    base: Path, tmp_path: Path, fail_on: str, caplog: pytest.LogCaptureFixture
) -> None:
    ws = _workspace(base, "ws-big", tmp_path)
    _authored_work(ws)
    _grow(ws)
    log: list[str] = []
    result = await _enforcer(
        base, _Docker(log, {"ws-big": "exec-big"}), _Archive(log, fail_on=fail_on)
    ).run_once()

    assert result.stopped == ()
    assert result.unpreserved == ("ws-big",)
    assert not any(entry.startswith("stop") for entry in log)
    assert log[0] == "freeze ws-big" and log[-1] == "thaw ws-big"  # the run carries on
    assert (ws / "artifacts" / "output" / "deliverable.md").exists()
    assert "NOT stopped, its work could not be saved" in caplog.text


class _AgentWritingDuringUpload(_Archive):
    """The agent keeps working while each upload is in flight, unless frozen.

    The freezer is the kernel's; this double models it by letting the "agent"
    write only while its container is not frozen.
    """

    def __init__(self, log: list[str], docker: _Docker, ws: Path) -> None:
        super().__init__(log)
        self._docker = docker
        self._ws = ws
        self._worked = False

    def _agent_works(self) -> None:
        """One late commit and a rewritten deliverable, during the first upload."""
        if self._worked or self._ws.name in self._docker.frozen:
            return
        self._worked = True
        app = self._ws / "repos" / "app"
        (app / "late.py").write_text("late = True\n")
        _git(app, "add", "late.py")
        _git(app, "commit", "-m", "late commit")
        (self._ws / "artifacts" / "output" / "deliverable.md").write_text("# NEW work\n")

    async def save(self, stale: StaleWorkspaceDir, repo: str, patch: bytes) -> str:
        result = await super().save(stale, repo, patch)
        self._agent_works()
        return result

    async def save_files(self, stale: StaleWorkspaceDir, tarball: bytes) -> str:
        result = await super().save_files(stale, tarball)
        self._agent_works()
        return result


async def test_every_byte_present_at_the_kill_is_in_the_archive(base: Path, tmp_path: Path) -> None:
    """#1805 reverify B1: no write lands between the snapshot and the kill."""
    ws = _workspace(base, "ws-big", tmp_path)
    _authored_work(ws)
    _grow(ws)
    log: list[str] = []
    docker = _Docker(log, {"ws-big": "exec-big"})
    archive = _AgentWritingDuringUpload(log, docker, ws)

    result = await _enforcer(base, docker, archive).run_once()

    assert result.stopped == ("ws-big",)
    app = ws / "repos" / "app"
    live_head = _git(app, "rev-parse", "HEAD").strip()
    bundle = next(v for k, v in archive.patches.items() if k.endswith(".bundle"))
    (tmp_path / "b.bundle").write_bytes(bundle)
    assert live_head in _git(tmp_path, "bundle", "list-heads", str(tmp_path / "b.bundle"))
    with tarfile.open(fileobj=io.BytesIO(archive.files[0]), mode="r:gz") as tar:
        member = tar.extractfile("artifacts/output/deliverable.md")
        assert member is not None
        archived = member.read()
    assert archived == (ws / "artifacts" / "output" / "deliverable.md").read_bytes()
    assert "ws-big" in docker.frozen  # killed while still frozen


async def test_a_workspace_that_cannot_be_frozen_is_not_touched(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-big", tmp_path)
    _authored_work(ws)
    _grow(ws)
    log: list[str] = []
    docker = _Docker(log, {"ws-big": "exec-big"}, freeze_fails=True)
    result = await _enforcer(base, docker, _Archive(log)).run_once()
    assert result.unpreserved == ("ws-big",)
    assert log == []


async def test_an_unowned_workspace_is_not_stopped(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-big", tmp_path)
    _grow(ws)
    log: list[str] = []
    result = await _enforcer(base, _Docker(log, {"ws-big": None}), _Archive(log)).run_once()  # type: ignore[dict-item]
    assert result.unpreserved == ("ws-big",)
    assert log == []


async def test_a_concurrent_workspace_under_the_cap_is_unaffected(
    base: Path, tmp_path: Path
) -> None:
    big = _workspace(base, "ws-big", tmp_path)
    small = _workspace(base, "ws-small", tmp_path)
    _authored_work(small)
    _grow(big)
    log: list[str] = []
    docker = _Docker(log, {"ws-big": "exec-big", "ws-small": "exec-small"})
    result = await _enforcer(base, docker, _Archive(log)).run_once()

    assert result.stopped == ("ws-big",)
    assert not any("ws-small" in entry for entry in log)


async def test_an_over_cap_dir_with_no_running_container_is_left_to_reclaim(
    base: Path, tmp_path: Path
) -> None:
    _grow(_workspace(base, "ws-big", tmp_path))
    log: list[str] = []
    result = await _enforcer(base, _Docker(log, {}), _Archive(log)).run_once()
    assert result.stopped == () and result.unpreserved == () and log == []


async def test_the_setting_reaches_the_enforcer_and_zero_turns_it_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[int] = []

    def fake_enforcer(limit_mb: int, is_live: object) -> object:
        built.append(limit_mb)
        return object()

    async def never(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(workspace_disk_cap, "default_enforcer", fake_enforcer)
    monkeypatch.setattr(workspace_disk_cap, "enforce_on_a_clock", never)

    monkeypatch.setenv("SYN_WORKSPACE_DISK_LIMIT_MB", "0")
    workspace_disk_cap.start_workspace_disk_cap(lambda: True)
    assert built == []

    monkeypatch.setenv("SYN_WORKSPACE_DISK_LIMIT_MB", "1234")
    workspace_disk_cap.start_workspace_disk_cap(lambda: True)
    await workspace_disk_cap.stop_workspace_disk_cap()
    assert built == [1234]
