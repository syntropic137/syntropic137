"""PC-130: workspace directories whose container is gone are reclaimed, guarded.

Every test drives `WorkspaceDirReclaimer.run_once` - the consumer - over real
directories holding real git repositories with a real (bare) remote, through
the real host-git adapter and the real domain guard. Only docker, the
execution projection and MinIO are doubles.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import subprocess
import tarfile
import time
from typing import TYPE_CHECKING

import pytest

from syn_adapters.workspace_backends import stale_dirs
from syn_adapters.workspace_backends.orphaned import ShutilWorkspaceDirRemover, parse_inspect
from syn_adapters.workspace_backends.stale_dirs import (
    SubprocessHostWorkspaceGit,
    WorkspaceContainer,
    archive_key,
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
        self.files: list[bytes] = []
        self._fail = fail

    async def save(self, stale: StaleWorkspaceDir, repo: str, patch: bytes) -> str:
        if self._fail:
            raise OSError("minio down")
        self.saved.append((stale.execution_id, patch))
        return f"s3://artifacts/{stale.execution_id}/reclaimed-{stale.workspace_id}.md"

    async def save_files(self, stale: StaleWorkspaceDir, tarball: bytes) -> str:
        if self._fail:
            raise OSError("minio down")
        self.files.append(tarball)
        return f"s3://artifacts/{stale.execution_id}/reclaimed-{stale.workspace_id}.tar.gz"


def _reclaimer(
    base: Path,
    *,
    containers: list[WorkspaceContainer] | None = None,
    running: set[str] | None = None,
    archive: _Archive | None = None,
    hours_later: float = 7.0,
    known_owner: bool = True,
) -> WorkspaceDirReclaimer:
    async def list_containers() -> list[WorkspaceContainer]:
        return containers or []

    async def running_ids() -> set[str]:
        return running or set()

    async def workspace_owners(workspace_id: str) -> set[str]:
        if not known_owner or containers:
            return set()
        return {"exec-fixture"}

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
        workspace_owners=workspace_owners,
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
    assert list(base.iterdir()) == []  # A rename alone is not reclamation.
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


async def test_no_pass_runs_while_catching_up(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _workspace(base, "ws-replay", tmp_path)
    reclaimer = _reclaimer(base)
    ran = asyncio.Event()
    run_once = reclaimer.run_once
    live = [False]

    async def observed_run_once() -> object:
        ran.set()
        return await run_once()

    monkeypatch.setattr(reclaimer, "run_once", observed_run_once)
    task = asyncio.create_task(
        reclaim_on_a_clock(reclaimer, is_live=lambda: live[0], interval_seconds=0.01)
    )
    try:
        await asyncio.sleep(0.1)
        ran_during_replay = ran.is_set()
        live[0] = True
        await asyncio.wait_for(ran.wait(), timeout=1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not ran_during_replay
    assert ran.is_set()
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


# --- Verification round 1 (PR #1755): shapes the first tests did not reach ---


def _tar_names(tarball: bytes) -> set[str]:
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
        return set(tar.getnames())


async def test_different_owner_repo_config_is_seen_and_its_filter_never_runs(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B1: listed without safe.directory, git drops the config and the scan sees nothing."""
    ws = _workspace(base, "ws-foreign", tmp_path)
    app = ws / "repos" / "app"
    marker = tmp_path / "filtered"
    _git(app, "config", "filter.pc130.clean", f"touch {marker}; cat")
    (app / ".gitattributes").write_text("README.md filter=pc130\n")
    (app / "README.md").write_text("changed\n")
    real_exec = asyncio.create_subprocess_exec

    async def as_another_owner(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        env = dict(kwargs.pop("env", None) or {})  # type: ignore[arg-type]
        env["GIT_TEST_ASSUME_DIFFERENT_OWNER"] = "1"
        return await real_exec(*args, env=env, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(stale_dirs.asyncio, "create_subprocess_exec", as_another_owner)
    result = await _reclaimer(base).run_once()
    assert result.kept == ("ws-foreign",)
    assert ws.exists()
    assert not marker.exists()


async def test_work_outside_any_repository_is_archived_before_deletion(
    base: Path, tmp_path: Path
) -> None:
    """B2: an agent's deliverable lives in artifacts/output, outside every repo."""
    ws = _workspace(base, "ws-output", tmp_path)
    (ws / "artifacts" / "output").mkdir(parents=True)
    (ws / "artifacts" / "output" / "only-copy.md").write_text("the deliverable\n")
    archive = _Archive()
    result = await _reclaimer(base, archive=archive).run_once()
    assert result.reclaimed == ("ws-output",)
    [tarball] = archive.files
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
        member = tar.extractfile("artifacts/output/only-copy.md")
        assert member is not None
        assert member.read() == b"the deliverable\n"


async def test_failed_unversioned_archive_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-output-nosave", tmp_path)
    (ws / "notes.md").write_text("only copy\n")
    result = await _reclaimer(base, archive=_Archive(fail=True)).run_once()
    assert result.kept == ("ws-output-nosave",)
    assert (ws / "notes.md").read_text() == "only copy\n"


async def test_ignored_files_are_archived_and_proven_caches_are_not(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-ignored", tmp_path)
    app = ws / "repos" / "app"
    (app / ".git" / "info" / "exclude").write_text("secret-notes.txt\nnode_modules/\n")
    (app / "secret-notes.txt").write_text("unique\n")
    (app / "package.json").write_text("{}\n")
    (app / "node_modules" / "pkg").mkdir(parents=True)
    (app / "node_modules" / "pkg" / "index.js").write_text("cache\n")
    (app / "node_modules" / "CACHEDIR.TAG").write_bytes(
        b"Signature: 8a477f597d28d172789f06886806bc55\n"
    )
    (ws / "package.json").write_text("{}\n")
    (ws / "node_modules" / "pkg").mkdir(parents=True)
    (ws / "node_modules" / "pkg" / "index.js").write_text("cache outside a repo\n")
    (ws / "node_modules" / "CACHEDIR.TAG").write_bytes(
        b"Signature: 8a477f597d28d172789f06886806bc55\n"
    )
    archive = _Archive()
    result = await _reclaimer(base, archive=archive).run_once()
    assert result.reclaimed == ("ws-ignored",)
    [tarball] = archive.files
    names = _tar_names(tarball)
    assert "repos/app/secret-notes.txt" in names
    assert not any("node_modules" in n for n in names)


async def test_a_cache_name_alone_does_not_make_authored_files_disposable(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-named", tmp_path)
    authored = {
        "target/only-copy.md": b"authored output, nowhere else\n",
        ".cache/notes.txt": b"also authored\n",
        "node_modules/orphan.js": b"no package.json reinstalls this\n",
    }
    for name, content in authored.items():
        (ws / name).parent.mkdir(parents=True, exist_ok=True)
        (ws / name).write_bytes(content)
    tagged = ws / "repos" / "app" / "target"
    tagged.mkdir()
    (tagged / "CACHEDIR.TAG").write_bytes(b"Signature: 8a477f597d28d172789f06886806bc55\n# cargo\n")
    (tagged / "build.o").write_bytes(b"regenerable\n")
    (ws / "repos" / "app" / ".git" / "info" / "exclude").write_text("target/\n")
    archive = _Archive()
    result = await _reclaimer(base, archive=archive).run_once()
    assert result.reclaimed == ("ws-named",)
    [tarball] = archive.files
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
        for name, content in authored.items():
            member = tar.extractfile(name)
            assert member is not None
            assert member.read() == content
        assert not any("build.o" in n for n in tar.getnames())


async def test_bare_repository_with_an_unpushed_branch_keeps_the_dir(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-bare", tmp_path)
    bare = ws / "repos" / "authored.git"
    _git(tmp_path, "clone", "--bare", str(tmp_path / "ws-bare-remote.git"), str(bare))
    work = tmp_path / "bare-work"
    _git(tmp_path, "clone", str(bare), str(work))
    (work / "local.txt").write_text("only here\n")
    _git(work, "add", "local.txt")
    _git(work, "commit", "-m", "local only")
    _git(work, "push", "origin", "HEAD:refs/heads/only-local")
    result = await _reclaimer(base).run_once()
    assert result.kept == ("ws-bare",)
    assert bare.exists()


async def test_stash_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-stash", tmp_path)
    app = ws / "repos" / "app"
    (app / "README.md").write_text("stashed work\n")
    _git(app, "stash")
    result = await _reclaimer(base).run_once()
    assert result.kept == ("ws-stash",)
    assert ws.exists()


async def test_index_that_differs_from_head_and_tree_keeps_the_dir(
    base: Path, tmp_path: Path
) -> None:
    """B3: staged then reverted: a HEAD-to-tree patch is empty, the index is not."""
    ws = _workspace(base, "ws-staged", tmp_path)
    app = ws / "repos" / "app"
    (app / "README.md").write_text("INDEX ONLY AUTHORED CONTENT\n")
    _git(app, "add", "README.md")
    (app / "README.md").write_text("hello\n")
    # Age the file and refresh the index now, as hours of grace would: a racily
    # clean index is rewritten by the guard's own git calls, which trips the
    # changed-during-archival check instead of the one under test.
    hours_ago = time.time() - 2 * 3600
    os.utime(app / "README.md", (hours_ago, hours_ago))
    subprocess.run(["git", "update-index", "-q", "--refresh"], cwd=app, check=False)
    archive = _Archive()
    result = await _reclaimer(base, archive=archive).run_once()
    assert result.kept == ("ws-staged",)
    assert ws.exists()


@pytest.mark.parametrize("running_first", [True, False])
async def test_any_running_mount_protects_the_dir_in_either_order(
    base: Path, tmp_path: Path, running_first: bool
) -> None:
    """B4: a stopped mount listed after a running one must not hide it."""
    ws = _workspace(base, "ws-twice", tmp_path)
    pair = [
        WorkspaceContainer(workspace_id="ws-twice", execution_id="exec-a", running=True),
        WorkspaceContainer(workspace_id="ws-twice", execution_id="exec-a", running=False),
    ]
    containers = pair if running_first else pair[::-1]
    result = await _reclaimer(base, containers=containers).run_once()
    assert result.reclaimed == ()
    assert ws.exists()


async def test_unknown_owner_waits_while_any_execution_is_running(
    base: Path, tmp_path: Path
) -> None:
    """B5: with its container removed nothing names the owner; it may be running."""
    ws = _workspace(base, "ws-anon", tmp_path)
    result = await _reclaimer(base, running={"exec-running"}, known_owner=False).run_once()
    assert result.reclaimed == ()
    assert ws.exists()


async def test_container_starting_during_archival_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    """B6: authorization is read again after the archive, not only before it."""
    ws = _workspace(base, "ws-race", tmp_path)
    (ws / "repos" / "app" / "README.md").write_text("dirty\n")
    containers = [WorkspaceContainer(workspace_id="ws-race", execution_id="exec-r", running=False)]

    class StartsContainer(_Archive):
        async def save(self, stale: StaleWorkspaceDir, repo: str, patch: bytes) -> str:
            containers[0] = WorkspaceContainer(
                workspace_id="ws-race", execution_id="exec-r", running=True
            )
            return await super().save(stale, repo, patch)

    result = await _reclaimer(base, containers=containers, archive=StartsContainer()).run_once()
    assert result.kept == ("ws-race",)
    assert ws.exists()


async def test_catch_up_beginning_during_archival_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-replay-race", tmp_path)
    (ws / "repos" / "app" / "README.md").write_text("dirty\n")
    live = [True]

    class CatchUpBegins(_Archive):
        async def save(self, stale: StaleWorkspaceDir, repo: str, patch: bytes) -> str:
            live[0] = False
            return await super().save(stale, repo, patch)

    reclaimer = _reclaimer(base, archive=CatchUpBegins())
    reclaimer.is_live = lambda: live[0]
    result = await reclaimer.run_once()
    assert result.kept == ("ws-replay-race",)
    assert ws.exists()


def test_archive_keys_never_collide_across_repository_paths() -> None:
    """B7: ``repos/a_b`` and ``repos/a/b`` once shared one object key."""
    from syn_domain.contexts.orchestration import StaleWorkspaceDir

    stale = StaleWorkspaceDir(
        host_dir="/w/ws-1", workspace_id="ws-1", execution_id=None, size_bytes=0
    )
    assert archive_key(stale, "/w/ws-1/repos/a_b") != archive_key(stale, "/w/ws-1/repos/a/b")


async def test_catch_up_or_a_live_mount_after_the_last_look_cannot_reach_the_dir(
    base: Path, tmp_path: Path
) -> None:
    """B6: the directory is claimed before the last look, so a later change finds nothing."""
    ws = _workspace(base, "ws-handoff", tmp_path)
    live = [True]
    reclaimer = _reclaimer(base)
    reclaimer.is_live = lambda: live[0]
    claim = reclaimer.claim

    def claim_then_catch_up(host_dir: str) -> str:
        claimed = claim(host_dir)
        live[0] = False
        return claimed

    reclaimer.claim = claim_then_catch_up
    result = await reclaimer.run_once()
    assert result.kept == ("ws-handoff",)
    assert ws.exists()
    assert sorted(p.name for p in base.iterdir()) == ["ws-handoff"]


async def test_a_container_arriving_at_the_claim_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-claim-race", tmp_path)
    containers: list[WorkspaceContainer] = []
    reclaimer = _reclaimer(base, containers=containers)
    claim = reclaimer.claim

    def claim_then_mount(host_dir: str) -> str:
        claimed = claim(host_dir)
        containers.append(
            WorkspaceContainer(workspace_id="ws-claim-race", execution_id="exec-c", running=True)
        )
        return claimed

    reclaimer.claim = claim_then_mount
    result = await reclaimer.run_once()
    assert result.kept == ("ws-claim-race",)
    assert ws.exists()


@pytest.mark.parametrize("authored", ["commit", "stash", "ref"])
async def test_git_work_authored_during_archival_keeps_the_dir(
    base: Path, tmp_path: Path, authored: str
) -> None:
    """B6: no worktree mtime moves, so only the git-state comparison sees it."""
    ws = _workspace(base, f"ws-during-{authored}", tmp_path)
    app = ws / "repos" / "app"
    (ws / "notes.md").write_text("outside any repository\n")

    class AuthorsDuringUpload(_Archive):
        async def save_files(self, stale: StaleWorkspaceDir, tarball: bytes) -> str:
            if authored == "commit":
                _git(app, "commit", "--allow-empty", "-m", "made during upload")
            elif authored == "stash":
                (app / "README.md").write_text("stashed during upload\n")
                _git(app, "stash")
            else:
                sha = subprocess.run(
                    [
                        "git",
                        "-c",
                        "user.email=t@t",
                        "-c",
                        "user.name=t",
                        "commit-tree",
                        "-p",
                        "HEAD",
                        "-m",
                        "new ref",
                        "HEAD^{tree}",
                    ],
                    cwd=app,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                _git(app, "update-ref", "refs/agent/keep", sha)
            return await super().save_files(stale, tarball)

    result = await _reclaimer(base, archive=AuthorsDuringUpload()).run_once()
    assert result.kept == (f"ws-during-{authored}",)
    assert ws.exists()


@pytest.mark.parametrize("running_owner", [False, True])
async def test_containerless_workspace_uses_replayed_ownership(
    base: Path, tmp_path: Path, running_owner: bool
) -> None:
    """B5: the real producer, replay and a new reader retain every phase's owner."""
    from event_sourcing import EventEnvelope, MemoryCheckpointStore, ProjectionResult
    from event_sourcing.core.envelope import decode_event, encode_payload, event_type_of

    from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        ProvisionWorkspaceCompletedCommand,
        StartExecutionCommand,
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.workspace_ownership.projection import (
        WorkspaceOwnershipProjection,
    )

    store = InMemoryProjectionStore()
    projection = WorkspaceOwnershipProjection(store)
    checkpoints = MemoryCheckpointStore()
    for execution_id, workspace_id in [("exec-first", "ws-first"), ("exec-second", "ws-second")]:
        ws = _workspace(base, workspace_id, tmp_path)
        (ws / "repos" / "app" / "README.md").write_text(f"only copy from {execution_id}\n")
        aggregate = WorkflowExecutionAggregate()
        aggregate._handle_command(
            StartExecutionCommand(
                execution_id=execution_id,
                workflow_id="wf",
                workflow_name="ownership",
                total_phases=1,
                inputs={},
            )
        )
        aggregate._handle_command(
            ProvisionWorkspaceCompletedCommand(
                execution_id=execution_id, phase_id="p", workspace_id=workspace_id
            )
        )
        envelope = aggregate._uncommitted_events[-1]
        # Serialize and decode as the event store does, then replay twice.
        event_type = event_type_of(envelope.event)
        decoded = decode_event(event_type, 1, encode_payload(envelope.event))
        envelope = EventEnvelope(
            event=decoded.event,
            metadata=envelope.metadata.model_copy(update={"event_type": decoded.event_type}),
        )
        for _ in range(2):
            assert await projection.handle_event(envelope, checkpoints) is ProjectionResult.SUCCESS
    reader = WorkspaceOwnershipProjection(store)
    archive = _Archive()
    reclaimer = _reclaimer(
        base, archive=archive, running={"exec-second"} if running_owner else set()
    )
    reclaimer.workspace_owners = reader.owners
    result = await reclaimer.run_once()
    for execution_id, workspace_id in [("exec-first", "ws-first"), ("exec-second", "ws-second")]:
        assert await reader.owners(workspace_id) == {execution_id}
        if running_owner and execution_id == "exec-second":
            assert (base / workspace_id).exists()
        else:
            assert workspace_id in result.reclaimed
            assert any(
                owner == execution_id and f"only copy from {execution_id}".encode() in patch
                for owner, patch in archive.saved
            )


@pytest.mark.parametrize("outside_repo", [False, True])
async def test_unidentified_authored_work_is_kept(
    base: Path, tmp_path: Path, outside_repo: bool
) -> None:
    ws = _workspace(base, "ws-unidentified", tmp_path)
    authored = ws / "notes.md" if outside_repo else ws / "repos" / "app" / "README.md"
    authored.write_text("no known owner, only copy\n")
    archive = _Archive()
    result = await _reclaimer(base, archive=archive, known_owner=False).run_once()
    assert result.kept == ("ws-unidentified",)
    assert ws.exists()
    assert not archive.saved
    assert not archive.files
