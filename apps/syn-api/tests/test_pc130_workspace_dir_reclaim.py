"""PC-130 / #1983: workspace directories are reclaimed only when deleting loses nothing.

Every test drives `WorkspaceDirReclaimer.run_once` - the consumer - over real
directories holding real git repositories with a real (bare) remote, through
the real host-git adapter, the real ``git ls-remote`` and the real domain
guard. Only docker, the read models and capture records are doubles.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from pathlib import Path

import pytest

from syn_adapters.workspace_backends import stale_dirs
from syn_adapters.workspace_backends.orphaned import parse_inspect
from syn_adapters.workspace_backends.reclaim_delete import AUTH_DIRNAME, authorize_and_mark
from syn_adapters.workspace_backends.remote_refs import GitLsRemote
from syn_adapters.workspace_backends.stale_dirs import (
    ContainerMounts,
    SubprocessHostWorkspaceGit,
    claim_workspace_dir,
    scan_workspace_dirs,
)
from syn_api.services.workspace_dir_reclaim import (
    ReclaimPass,
    WorkspaceDirReclaimer,
    reclaim_on_a_clock,
)
from syn_domain.contexts.orchestration import OwnerExecution, RetainedReason

pytestmark = pytest.mark.unit

_SETTLE = 600.0


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _remote(tmp_path: Path, workspace_id: str) -> Path:
    return tmp_path / f"{workspace_id}-remote.git"


def _workspace(base: Path, workspace_id: str, tmp_path: Path) -> Path:
    """A workspace dir holding one repo cloned from a bare remote, fully pushed."""
    remote = _remote(tmp_path, workspace_id)
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


def _owner(workspace_id: str) -> str:
    return f"exec-{workspace_id.removeprefix(stale_dirs.CLAIM_PREFIX)}"


def _reclaimer(
    base: Path,
    *,
    containers: list[ContainerMounts] | None = None,
    status: str = "completed",
    ended_seconds_ago: float = 3600.0,
    known_owner: bool = True,
    extra_remotes: tuple[str, ...] = (),
    name_remote: bool = True,
    capture: str | None = None,
) -> WorkspaceDirReclaimer:
    """Every directory is owned by ``exec-<workspace_id>``, whose record names its remote."""
    tmp_path = base.parent

    async def list_containers() -> list[ContainerMounts]:
        return containers or []

    async def workspace_owners(workspace_id: str) -> set[str]:
        return {_owner(workspace_id)} if known_owner else set()

    async def execution_record(execution_id: str) -> OwnerExecution | None:
        workspace_id = execution_id.removeprefix("exec-")
        named = (str(_remote(tmp_path, workspace_id)),) if name_remote else ()
        terminal = status in {"completed", "failed", "cancelled"}
        return OwnerExecution(
            execution_id=execution_id,
            status=status,
            terminal_at=time.time() - ended_seconds_ago if terminal else None,
            repositories=named + extra_remotes,
        )

    async def capture_unproven(execution_id: str) -> str | None:
        return capture

    return WorkspaceDirReclaimer(
        base_dir=str(base),
        settle_seconds=_SETTLE,
        list_containers=list_containers,
        workspace_owners=workspace_owners,
        execution_record=execution_record,
        capture_unproven=capture_unproven,
        scan_dirs=scan_workspace_dirs,
        git=SubprocessHostWorkspaceGit(),
        remotes=GitLsRemote(),
        host_base_dir=HOST_BASE,
        own_container="api0000000001",
    )


#: Where docker names the workspace base on the host, in every test.
HOST_BASE = "/srv/workspaces"


def _reason(result: ReclaimPass, workspace_id: str) -> RetainedReason:
    [kept] = [r for r in result.retained if r.workspace_id == workspace_id]
    return kept.reason


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "workspaces"
    path.mkdir()
    return path


# --- the eligible path ---


async def test_clean_pushed_settled_dir_is_reclaimed_and_logged_with_size(
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
    assert "WorkspaceReclaimOutcome workspace_id=ws-clean" in caplog.text


async def test_a_fresh_mtime_does_not_hold_a_settled_dir(base: Path, tmp_path: Path) -> None:
    """Eligibility is the terminal event, never file times (G3)."""
    ws = _workspace(base, "ws-touched", tmp_path)
    future = time.time() + 3600
    os.utime(ws / "repos" / "app" / "README.md", (future, future))
    result = await _reclaimer(base).run_once()
    assert result.reclaimed == ("ws-touched",)


async def test_a_cachedir_tagged_tree_alone_does_not_hold_a_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-cache", tmp_path)
    cache = ws / "repos" / "app" / "target"
    cache.mkdir()
    (cache / "CACHEDIR.TAG").write_bytes(b"Signature: 8a477f597d28d172789f06886806bc55\n")
    (cache / "build.o").write_bytes(b"regenerable\n")
    (ws / "repos" / "app" / ".git" / "info" / "exclude").write_text("target/\n")
    result = await _reclaimer(base).run_once()
    assert result.reclaimed == ("ws-cache",)


async def test_dry_run_reports_what_it_would_reclaim_and_touches_nothing(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-dry", tmp_path)
    reclaimer = _reclaimer(base)
    reclaimer.dry_run = True
    result = await reclaimer.run_once()
    assert result.would_reclaim == ("ws-dry",)
    assert result.reclaimed == ()
    assert sorted(p.name for p in base.iterdir()) == ["ws-dry"]
    assert ws.exists()


# --- owner finished: unowned, not_terminal ---


@pytest.mark.parametrize(
    ("status", "ended", "why"),
    [
        ("running", 3600.0, "is running"),
        ("interrupted", 3600.0, "is interrupted"),
        ("completed", 60.0, "settles after 600s"),
        ("failed", 60.0, "settles after 600s"),
    ],
)
async def test_an_owner_not_terminal_or_not_settled_keeps_the_dir(
    base: Path, tmp_path: Path, status: str, ended: float, why: str
) -> None:
    ws = _workspace(base, "ws-young", tmp_path)
    result = await _reclaimer(base, status=status, ended_seconds_ago=ended).run_once()
    assert _reason(result, "ws-young") is RetainedReason.NOT_TERMINAL
    assert why in result.retained[0].detail
    assert ws.exists()


async def test_a_missing_execution_record_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-norecord", tmp_path)
    reclaimer = _reclaimer(base)

    async def no_record(execution_id: str) -> OwnerExecution | None:
        return None

    reclaimer.execution_record = no_record
    result = await reclaimer.run_once()
    assert _reason(result, "ws-norecord") is RetainedReason.NOT_TERMINAL
    assert ws.exists()


async def test_a_terminal_record_without_a_terminal_time_keeps_the_dir(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-notime", tmp_path)
    reclaimer = _reclaimer(base)

    async def untimed(execution_id: str) -> OwnerExecution | None:
        return OwnerExecution(execution_id, "cancelled", None, ())

    reclaimer.execution_record = untimed
    result = await reclaimer.run_once()
    assert _reason(result, "ws-notime") is RetainedReason.NOT_TERMINAL
    assert ws.exists()


async def test_no_owner_keeps_the_dir_whatever_else_runs(base: Path, tmp_path: Path) -> None:
    """G2: an unowned directory is never a candidate, not merely while runs are in flight."""
    ws = _workspace(base, "ws-anon", tmp_path)
    result = await _reclaimer(base, known_owner=False).run_once()
    assert _reason(result, "ws-anon") is RetainedReason.UNOWNED
    assert ws.exists()


async def test_two_owners_keep_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-two", tmp_path)
    reclaimer = _reclaimer(base)

    async def owners(workspace_id: str) -> set[str]:
        return {"exec-first", "exec-second"}

    reclaimer.workspace_owners = owners
    result = await reclaimer.run_once()
    assert _reason(result, "ws-two") is RetainedReason.UNOWNED
    assert ws.exists()


# --- not mounted: every container, any state, any destination ---


@pytest.mark.parametrize("running", [True, False])
@pytest.mark.parametrize(
    "source",
    [
        "/srv/workspaces/{ws}",
        "/srv/workspaces/{ws}/repos/app",
        "/srv/workspaces/.reclaiming-{ws}",
    ],
)
async def test_any_container_binding_the_dir_or_below_keeps_it(
    base: Path, tmp_path: Path, running: bool, source: str
) -> None:
    ws = _workspace(base, "ws-bound", tmp_path)
    # Not an agentic-ws- container, not at /workspace: any bind counts.
    bound = ContainerMounts("sidecar01", (source.format(ws="ws-bound"),), running=running)
    result = await _reclaimer(base, containers=[bound]).run_once()
    assert _reason(result, "ws-bound") is RetainedReason.MOUNTED
    assert ws.exists()


async def test_only_this_process_own_bind_of_the_base_is_exempt(base: Path, tmp_path: Path) -> None:
    """The API binds the whole base; its own container, and only it, may."""
    _workspace(base, "ws-base-bound", tmp_path)
    own = ContainerMounts("api0000000001ffff", ("/srv/workspaces", "/var/run/docker.sock"))
    result = await _reclaimer(base, containers=[own]).run_once()
    assert result.reclaimed == ("ws-base-bound",)


@pytest.mark.parametrize("source", ["/srv/workspaces", "/srv/workspaces/", "/srv", "/"])
async def test_another_container_binding_the_base_or_an_ancestor_keeps_every_dir(
    base: Path, tmp_path: Path, source: str
) -> None:
    """Codex r1 finding 5: through an ancestor bind a container reaches every workspace,
    under any name, so it blocks deletion like a direct bind."""
    ws = _workspace(base, "ws-ancestor", tmp_path)
    other = ContainerMounts("tool0000000002", (source,), running=True)
    result = await _reclaimer(base, containers=[other]).run_once()
    assert _reason(result, "ws-ancestor") is RetainedReason.MOUNTED
    assert ws.exists()


async def test_an_unknown_host_base_keeps_every_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-no-host-base", tmp_path)
    reclaimer = _reclaimer(base)
    reclaimer.host_base_dir = None
    result = await reclaimer.run_once()
    assert _reason(result, "ws-no-host-base") is RetainedReason.MOUNTED
    assert ws.exists()


def test_inspect_reads_whether_the_container_is_running_and_every_mount() -> None:
    raw = (
        '[{"State": {"Running": false, "OOMKilled": true},'
        ' "Config": {"Labels": {"syn.execution_id": "e"}},'
        ' "Mounts": [{"Destination": "/workspace", "Source": "/w/ws-1"},'
        ' {"Destination": "/data", "Source": "/w/ws-2/sub"}]}]'
    )
    inspected = parse_inspect(raw)
    assert inspected is not None
    assert inspected.running is False
    assert inspected.mount_sources == ("/w/ws-1", "/w/ws-2/sub")
    assert parse_inspect(raw.replace('"Running": false', '"Running": true')).running is True  # type: ignore[union-attr]
    # No mount list is "unknown", not "no mounts".
    assert parse_inspect('[{"State": {}}]').mount_sources is None  # type: ignore[union-attr]


async def test_unreadable_docker_skips_the_whole_pass(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-unknown", tmp_path)
    reclaimer = _reclaimer(base)

    async def docker_down() -> list[ContainerMounts]:
        raise RuntimeError("docker unreachable")

    reclaimer.list_containers = docker_down
    result = await reclaimer.run_once()
    assert result.skipped is not None
    assert ws.exists()


# --- fully readable ---


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 directory")
async def test_a_subdirectory_this_process_cannot_list_keeps_the_dir(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-locked", tmp_path)
    locked = ws / "locked"
    locked.mkdir()
    (locked / "only-copy.md").write_text("unique bytes nobody else holds\n")
    locked.chmod(0)
    try:
        result = await _reclaimer(base).run_once()
    finally:
        locked.chmod(0o700)
    assert _reason(result, "ws-locked") is RetainedReason.UNREADABLE
    assert (locked / "only-copy.md").read_text() == "unique bytes nobody else holds\n"


# --- no dirty work: dirty, unversioned, stash (nothing is archived) ---


@pytest.mark.parametrize("change", ["edited", "untracked", "staged"])
async def test_uncommitted_work_keeps_the_dir_and_nothing_is_archived(
    base: Path, tmp_path: Path, change: str
) -> None:
    ws = _workspace(base, f"ws-{change}", tmp_path)
    app = ws / "repos" / "app"
    if change == "edited":
        (app / "README.md").write_text("hello\nedited by the agent\n")
    elif change == "untracked":
        (app / "new.py").write_text("print('only copy')\n")
    else:
        (app / "staged.py").write_text("x = 1\n")
        _git(app, "add", "staged.py")
    result = await _reclaimer(base).run_once()
    assert _reason(result, f"ws-{change}") is RetainedReason.DIRTY
    assert ws.exists()


async def test_index_that_differs_from_head_and_tree_keeps_the_dir(
    base: Path, tmp_path: Path
) -> None:
    """Staged then reverted: a HEAD-to-tree patch is empty, the index is not."""
    ws = _workspace(base, "ws-index", tmp_path)
    app = ws / "repos" / "app"
    (app / "README.md").write_text("INDEX ONLY AUTHORED CONTENT\n")
    _git(app, "add", "README.md")
    (app / "README.md").write_text("hello\n")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-index") is RetainedReason.DIRTY
    assert ws.exists()


async def test_stash_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-stash", tmp_path)
    app = ws / "repos" / "app"
    (app / "README.md").write_text("stashed work\n")
    _git(app, "stash")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-stash") is RetainedReason.STASH
    assert ws.exists()


@pytest.mark.parametrize(
    "authored",
    [
        "artifacts/output/only-copy.md",
        "notes.md",
        "target/only-copy.md",
        ".cache/notes.txt",
        "repos/app/secret-notes.txt",
    ],
)
async def test_a_file_no_repository_holds_keeps_the_dir(
    base: Path, tmp_path: Path, authored: str
) -> None:
    """Outside every repository, or ignored by one: a name alone proves no cache."""
    ws = _workspace(base, "ws-unversioned", tmp_path)
    (ws / "repos" / "app" / ".git" / "info" / "exclude").write_text("secret-notes.txt\n")
    (ws / authored).parent.mkdir(parents=True, exist_ok=True)
    (ws / authored).write_text("the deliverable\n")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-unversioned") is RetainedReason.UNVERSIONED
    assert authored in result.retained[0].detail
    assert (ws / authored).read_text() == "the deliverable\n"


# --- commits on the real remote ---


async def test_unpushed_commit_on_a_branch_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-unpushed", tmp_path)
    app = ws / "repos" / "app"
    _git(app, "checkout", "-b", "agent-work")
    (app / "feature.py").write_text("x = 1\n")
    _git(app, "add", "feature.py")
    _git(app, "commit", "-m", "never pushed")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-unpushed") is RetainedReason.UNPUSHED_UNPROVEN
    assert ws.exists()


async def test_unpushed_commit_on_a_detached_head_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-detached", tmp_path)
    app = ws / "repos" / "app"
    _git(app, "checkout", "--detach")
    (app / "f.py").write_text("y = 2\n")
    _git(app, "add", "f.py")
    _git(app, "commit", "-m", "detached")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-detached") is RetainedReason.UNPUSHED_UNPROVEN
    assert ws.exists()


async def test_a_local_remote_tracking_ref_is_not_proof(base: Path, tmp_path: Path) -> None:
    """Codex round 2 (d): ``refs/remotes/*`` is a file the agent could write."""
    ws = _workspace(base, "ws-forged", tmp_path)
    app = ws / "repos" / "app"
    _git(app, "checkout", "-b", "agent-work")
    (app / "feature.py").write_text("x = 1\n")
    _git(app, "add", "feature.py")
    _git(app, "commit", "-m", "never pushed")
    _git(app, "update-ref", "refs/remotes/origin/agent-work", "HEAD")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-forged") is RetainedReason.UNPUSHED_UNPROVEN
    assert ws.exists()


async def test_a_remote_named_only_in_git_config_is_not_proof(base: Path, tmp_path: Path) -> None:
    """The repository's ``remote.origin.url`` is agent-written; the record names none."""
    ws = _workspace(base, "ws-config-remote", tmp_path)
    result = await _reclaimer(base, name_remote=False).run_once()
    assert _reason(result, "ws-config-remote") is RetainedReason.UNPUSHED_UNPROVEN
    assert "names no repository" in result.retained[0].detail
    assert ws.exists()


async def test_a_commit_pushed_to_another_remote_is_not_proof(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-elsewhere", tmp_path)
    app = ws / "repos" / "app"
    elsewhere = tmp_path / "elsewhere.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(elsewhere))
    (app / "feature.py").write_text("x = 1\n")
    _git(app, "add", "feature.py")
    _git(app, "commit", "-m", "pushed to the wrong place")
    _git(app, "push", str(elsewhere), "HEAD:main")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-elsewhere") is RetainedReason.UNPUSHED_UNPROVEN
    assert ws.exists()


async def test_an_unreadable_remote_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-noremote", tmp_path)
    reclaimer = _reclaimer(base)

    async def execution_record(execution_id: str) -> OwnerExecution | None:
        return OwnerExecution(
            execution_id, "completed", time.time() - 3600, (str(tmp_path / "gone.git"),)
        )

    reclaimer.execution_record = execution_record
    result = await reclaimer.run_once()
    assert _reason(result, "ws-noremote") is RetainedReason.UNPUSHED_UNPROVEN
    assert "ls-remote" in result.retained[0].detail
    assert ws.exists()


async def test_an_ls_remote_timeout_keeps_the_dir(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _workspace(base, "ws-slow", tmp_path)
    reclaimer = _reclaimer(base)
    reclaimer.remotes = GitLsRemote(timeout=0.3)
    real_exec = asyncio.create_subprocess_exec

    async def hanging_ls_remote(*argv: str, **kwargs: object) -> asyncio.subprocess.Process:
        if "ls-remote" in argv:
            return await real_exec("sleep", "5", **kwargs)  # type: ignore[arg-type]
        return await real_exec(*argv, **kwargs)  # type: ignore[arg-type]

    from syn_adapters.workspace_backends import remote_refs

    monkeypatch.setattr(remote_refs.asyncio, "create_subprocess_exec", hanging_ls_remote)
    result = await reclaimer.run_once()
    assert _reason(result, "ws-slow") is RetainedReason.UNPUSHED_UNPROVEN
    assert "timed out" in result.retained[0].detail
    assert ws.exists()


async def test_bare_repository_with_an_unpushed_branch_keeps_the_dir(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-bare", tmp_path)
    bare = ws / "repos" / "authored.git"
    _git(tmp_path, "clone", "--bare", str(_remote(tmp_path, "ws-bare")), str(bare))
    work = tmp_path / "bare-work"
    _git(tmp_path, "clone", str(bare), str(work))
    (work / "local.txt").write_text("only here\n")
    _git(work, "add", "local.txt")
    _git(work, "commit", "-m", "local only")
    _git(work, "push", "origin", "HEAD:refs/heads/only-local")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-bare") is RetainedReason.UNPUSHED_UNPROVEN
    assert bare.exists()


# --- capture absent from the dir ---


async def test_a_session_store_anywhere_inside_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-capture", tmp_path)
    store = ws / "repos" / "app" / "deep" / ".agentic-session-store"
    store.mkdir(parents=True)
    (store / "envelope.jsonl").write_text("{}\n")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-capture") is RetainedReason.CAPTURE_UNKNOWN
    assert ws.exists()


async def test_a_session_store_at_the_spool_root_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    """AW's in-workspace example, ``SPOOL=/workspace``: ``<dir>/.agentic-session-store`` (#2095)."""
    ws = _workspace(base, "ws-spool-root", tmp_path)
    store = ws / stale_dirs.SESSION_STORE_DIRNAME / "repos"
    store.mkdir(parents=True)
    (store.parent / ".owner").write_text("agentic-session-store-metadata-v1\n")
    (store / "state.json").write_text("{}\n")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-spool-root") is RetainedReason.CAPTURE_UNKNOWN
    assert ws.exists()


def _pytest_fixture_store(ws: Path) -> Path:
    """Where the live leak put one (#2095): this file's own fixture, run inside a workspace."""
    return (
        ws
        / ".tmp"
        / "pytest-of-agent"
        / "pytest-7"
        / "test_a_session_store_anywhere_0"
        / "workspaces"
        / "ws-capture"
        / "repos"
        / "app"
        / "deep"
        / stale_dirs.SESSION_STORE_DIRNAME
    )


def test_a_session_store_inside_a_pytest_temp_tree_is_not_capture(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-ran-tests", tmp_path)
    [before] = scan_workspace_dirs(str(base))
    store = _pytest_fixture_store(ws)
    store.mkdir(parents=True)
    (store / "envelope.jsonl").write_text("{}\n")
    [listing] = scan_workspace_dirs(str(base))
    assert listing.session_store is False
    assert listing.unreadable is None
    assert listing.size_bytes - before.size_bytes == len("{}\n")  # still walked and sized


def test_a_pytest_temp_tree_does_not_hide_a_store_beside_it(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-both", tmp_path)
    _pytest_fixture_store(ws).mkdir(parents=True)
    (ws / ".tmp" / stale_dirs.SESSION_STORE_DIRNAME).mkdir()
    [listing] = scan_workspace_dirs(str(base))
    assert listing.session_store is True


async def test_a_pytest_fixture_store_alone_is_not_retained_as_capture(
    base: Path, tmp_path: Path
) -> None:
    """The capture clause passes; the temp tree is then judged as files like any other.

    A name proves nothing about disposability (`_is_proven_cache`), and pytest
    writes no CACHEDIR.TAG into its temp tree, so it is unversioned work.
    """
    ws = _workspace(base, "ws-fixture-only", tmp_path)
    store = _pytest_fixture_store(ws)
    store.mkdir(parents=True)
    (store / "envelope.jsonl").write_text("{}\n")
    result = await _reclaimer(base).run_once()
    [kept] = [r for r in result.retained if r.workspace_id == "ws-fixture-only"]
    assert kept.reason is RetainedReason.UNVERSIONED
    assert ".tmp/pytest-of-agent/" in kept.detail


async def test_capture_records_that_do_not_cover_every_session_keep_the_dir(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-noinventory", tmp_path)
    result = await _reclaimer(base, capture="1 session(s) have no spool capture").run_once()
    assert _reason(result, "ws-noinventory") is RetainedReason.CAPTURE_UNKNOWN
    assert ws.exists()


async def test_unreadable_capture_records_keep_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-captureerr", tmp_path)
    reclaimer = _reclaimer(base)

    async def unreadable(execution_id: str) -> str | None:
        raise OSError("inventory database unavailable")

    reclaimer.capture_unproven = unreadable
    result = await reclaimer.run_once()
    assert _reason(result, "ws-captureerr") is RetainedReason.CAPTURE_UNKNOWN
    assert ws.exists()


# --- the claim, the second look, the delete ---


async def test_a_container_arriving_at_the_claim_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-claim-race", tmp_path)
    containers: list[ContainerMounts] = []
    reclaimer = _reclaimer(base, containers=containers)
    claim = reclaimer.claim

    def claim_then_mount(host_dir: str) -> str:
        claimed = claim(host_dir)
        containers.append(ContainerMounts("late01", ("/srv/workspaces/ws-claim-race",)))
        return claimed

    reclaimer.claim = claim_then_mount
    result = await reclaimer.run_once()
    assert _reason(result, "ws-claim-race") is RetainedReason.MOUNTED
    assert ws.exists()


async def test_work_written_at_the_claim_keeps_the_dir(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-late-write", tmp_path)
    reclaimer = _reclaimer(base)
    claim = reclaimer.claim

    def claim_then_write(host_dir: str) -> str:
        claimed = claim(host_dir)
        (Path(claimed) / "late.md").write_text("written after the first look\n")
        return claimed

    reclaimer.claim = claim_then_write
    result = await reclaimer.run_once()
    assert _reason(result, "ws-late-write") is RetainedReason.UNVERSIONED
    assert (ws / "late.md").read_text() == "written after the first look\n"


async def test_a_directory_replaced_under_the_claim_is_not_deleted(
    base: Path, tmp_path: Path
) -> None:
    _workspace(base, "ws-swapped", tmp_path)
    moved = tmp_path / "moved-away"
    reclaimer = _reclaimer(base)
    claim = reclaimer.claim

    def claim_then_swap(host_dir: str) -> str:
        claimed = claim(host_dir)
        Path(claimed).rename(moved)
        _git(tmp_path, "clone", str(_remote(tmp_path, "ws-swapped")), claimed)
        return claimed

    reclaimer.claim = claim_then_swap
    result = await reclaimer.run_once()
    assert _reason(result, "ws-swapped") is RetainedReason.IDENTITY_CHANGED
    assert moved.is_dir()
    assert (base / "ws-swapped").is_dir()


async def test_catch_up_beginning_at_the_claim_keeps_the_dir(base: Path, tmp_path: Path) -> None:
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


async def test_a_failed_delete_is_reported(base: Path, tmp_path: Path) -> None:
    _workspace(base, "ws-root-owned", tmp_path)
    reclaimer = _reclaimer(base)

    def refuses(path: str, identity: tuple[int, int], deadline: float) -> bool:
        raise PermissionError(13, "Permission denied", path)

    reclaimer.delete_tree = refuses
    result = await reclaimer.run_once()
    assert _reason(result, "ws-root-owned") is RetainedReason.DELETE_FAILED
    # Proven before the delete began, so it is not put back: the next pass retries.
    assert sorted(p.name for p in base.iterdir()) == [".deleting-ws-root-owned", AUTH_DIRNAME]


# --- maintenance pauses every pass ---


async def test_maintenance_pauses_the_pass_before_it_looks(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-maint", tmp_path)
    reclaimer = _reclaimer(base)

    async def maintenance() -> str | None:
        return "maintenance"

    reclaimer.paused = maintenance
    result = await reclaimer.run_once()
    assert result.paused == "maintenance"
    assert result.reclaimed == ()
    assert ws.exists()


async def test_maintenance_set_mid_pass_stops_before_the_next_directory(
    base: Path, tmp_path: Path
) -> None:
    first = _workspace(base, "ws-a", tmp_path)
    second = _workspace(base, "ws-b", tmp_path)
    reclaimer = _reclaimer(base)
    # The pass start, then before ws-a and before each of its claim, mark and delete.
    answers = iter([None, None, None, None, None, "maintenance"])

    async def maintenance() -> str | None:
        return next(answers, "maintenance")

    reclaimer.paused = maintenance
    result = await reclaimer.run_once()
    assert result.reclaimed == ("ws-a",)
    assert result.paused == "maintenance"
    assert not first.exists()
    assert second.exists()


# --- host git stays inside the workspace and runs only allowlisted config ---


async def test_repo_config_naming_a_command_is_never_run_and_keeps_the_dir(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-hostile", tmp_path)
    app = ws / "repos" / "app"
    marker = tmp_path / "pwned"
    _git(app, "config", "core.fsmonitor", f"touch {marker}; false")
    (app / "README.md").write_text("changed\n")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-hostile") is RetainedReason.UNREADABLE
    assert ws.exists()
    assert not marker.exists()


async def test_different_owner_repo_config_is_seen_and_its_filter_never_runs(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Listed without safe.directory, git drops the config and the scan sees nothing."""
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


async def test_no_pass_runs_while_catching_up(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _workspace(base, "ws-replay", tmp_path)
    reclaimer = _reclaimer(base)
    ran = asyncio.Event()
    run_once = reclaimer.run_once
    live = [False]

    async def observed_run_once() -> ReclaimPass:
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


async def test_the_pressure_event_starts_a_pass_before_the_interval(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workspace(base, "ws-pressure", tmp_path)
    reclaimer = _reclaimer(base)
    ran = asyncio.Event()
    run_once = reclaimer.run_once

    async def observed_run_once() -> ReclaimPass:
        ran.set()
        return await run_once()

    monkeypatch.setattr(reclaimer, "run_once", observed_run_once)
    wake = asyncio.Event()
    task = asyncio.create_task(
        reclaim_on_a_clock(reclaimer, is_live=lambda: True, interval_seconds=3600, wake=wake)
    )
    try:
        await asyncio.sleep(0.05)
        assert not ran.is_set()
        wake.set()
        await asyncio.wait_for(ran.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# --- #1807 (kept from PC-130): host git stays inside the workspace and runs only allowlisted config ---


def _outside_repo(tmp_path: Path) -> Path:
    """A repository outside every workspace, with one commit a remote-tracking ref holds."""
    outside = tmp_path / "outside"
    _git(tmp_path, "init", "-b", "main", str(outside))
    (outside / "README.md").write_text("outside\n")
    _git(outside, "add", "README.md")
    _git(outside, "commit", "-m", "outside")
    _git(outside, "update-ref", "refs/remotes/origin/main", "HEAD")
    return outside


async def test_a_gitdir_file_pointing_outside_the_workspace_is_refused_and_kept(
    base: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ws = _workspace(base, "ws-gitdir", tmp_path)
    outside = _outside_repo(tmp_path)
    pointed = ws / "repos" / "pointed"
    pointed.mkdir()
    (pointed / ".git").write_text(f"gitdir: {outside / '.git'}\n")
    (pointed / "README.md").write_text("edited through the pointer\n")
    result = await _reclaimer(base).run_once()
    assert result.kept == ("ws-gitdir",)
    assert ws.exists()
    assert f"{pointed} reads {outside / '.git'}, outside the workspace" in caplog.text


async def test_a_core_worktree_outside_the_workspace_is_refused_and_kept(
    base: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ws = _workspace(base, "ws-worktree", tmp_path)
    secret_dir = tmp_path / "host-secrets"
    secret_dir.mkdir()
    (secret_dir / "host_secret.txt").write_text("not the workspace's\n")
    _git(ws / "repos" / "app", "config", "core.worktree", str(secret_dir))
    result = await _reclaimer(base).run_once()
    assert result.kept == ("ws-worktree",)
    assert ws.exists()
    assert "has a core.worktree other than itself" in caplog.text


async def test_git_never_searches_above_a_found_repository(
    base: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A directory shaped like a bare clone but not one must not resolve to an enclosing repo."""
    _outside_repo(tmp_path)
    # The workspace base is inside that clean, "pushed" repository.
    enclosed = tmp_path / "outside" / "workspaces"
    enclosed.mkdir()
    ws = _workspace(enclosed, "ws-climb", tmp_path)
    fake = ws / "repos" / "fake.git"
    for sub in ("objects", "refs"):
        (fake / sub).mkdir(parents=True)
    (fake / "HEAD").write_text("not a ref\n")
    (fake / "notes.txt").write_text("only copy\n")
    result = await _reclaimer(enclosed).run_once()
    assert result.kept == ("ws-climb",)
    assert (fake / "notes.txt").read_text() == "only copy\n"
    # Kept because git found no repository there, not by luck in the enclosing one.
    assert "not a git repository" in caplog.text


_RISKY_CONFIG = [
    ("core.alternateRefsCommand", "touch {marker}"),
    ("core.sshCommand", "touch {marker}"),
    ("credential.helper", "!touch {marker}"),
    ("credential.https://example.com.helper", "!touch {marker}"),
    ("diff.pc130.command", "touch {marker}"),
    ("diff.external", "touch {marker}"),
    ("gpg.ssh.program", "touch {marker}"),
    ("uploadpack.packObjectsHook", "touch {marker}"),
    ("core.pager", "touch {marker}; cat"),
    ("extensions.partialClone", "origin"),
    ("url.file:///tmp/.insteadOf", "https://"),
]


@pytest.mark.parametrize(("key", "value"), _RISKY_CONFIG)
async def test_a_config_key_outside_the_allowlist_is_refused_and_kept(
    base: Path, tmp_path: Path, key: str, value: str
) -> None:
    ws = _workspace(base, "ws-risky", tmp_path)
    app = ws / "repos" / "app"
    marker = tmp_path / "pwned"
    _git(app, "config", key, value.format(marker=marker))
    (app / "README.md").write_text("changed\n")
    result = await _reclaimer(base).run_once()
    assert result.kept == ("ws-risky",)
    assert ws.exists()
    assert not marker.exists()


@pytest.mark.parametrize("attribute", ["filter", "diff"])
async def test_a_filter_or_textconv_never_runs_and_keeps_the_dir(
    base: Path, tmp_path: Path, attribute: str
) -> None:
    ws = _workspace(base, f"ws-{attribute}", tmp_path)
    app = ws / "repos" / "app"
    marker = tmp_path / "pwned"
    key = "filter.pc130.clean" if attribute == "filter" else "diff.pc130.textconv"
    _git(app, "config", key, f"touch {marker}; cat")
    (app / ".gitattributes").write_text(f"* {attribute}=pc130\n")
    (app / "README.md").write_text("changed\n")
    result = await _reclaimer(base).run_once()
    assert result.kept == (f"ws-{attribute}",)
    assert not marker.exists()


@pytest.mark.parametrize("directive", ["include.path", "includeIf.gitdir:/.path"])
async def test_an_included_config_never_takes_effect(
    base: Path, tmp_path: Path, directive: str
) -> None:
    """Even one whose contents are all allowlisted: it is read from outside the workspace."""
    ws = _workspace(base, "ws-include", tmp_path)
    app = ws / "repos" / "app"
    included = tmp_path / "included.gitconfig"
    included.write_text("[user]\n\tname = harmless\n")
    _git(app, "config", directive, str(included))
    result = await _reclaimer(base).run_once()
    assert result.kept == ("ws-include",)
    assert ws.exists()


async def test_a_linked_worktree_whose_commondir_is_outside_is_refused_and_kept(
    base: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ws = _workspace(base, "ws-commondir", tmp_path)
    outside = _outside_repo(tmp_path)
    linked = ws / "repos" / "linked"
    _git(outside, "worktree", "add", "-b", "linked", str(linked))
    # Its git dir moved into the workspace; only `commondir` still leads out.
    git_dir = ws / ".linked-git"
    (outside / ".git" / "worktrees" / "linked").rename(git_dir)
    (git_dir / "commondir").write_text(f"{outside / '.git'}\n")
    (linked / ".git").write_text(f"gitdir: {git_dir}\n")
    result = await _reclaimer(base).run_once()
    assert result.kept == ("ws-commondir",)
    assert f"{linked} reads {outside / '.git'}, outside the workspace" in caplog.text


async def test_alternates_outside_the_workspace_are_refused_and_kept(
    base: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ws = _workspace(base, "ws-alternates", tmp_path)
    outside = _outside_repo(tmp_path)
    app = ws / "repos" / "app"
    (app / ".git" / "objects" / "info" / "alternates").write_text(
        f"{outside / '.git' / 'objects'}\n"
    )
    result = await _reclaimer(base).run_once()
    assert result.kept == ("ws-alternates",)
    assert f"{app} reads {outside / '.git' / 'objects'}, outside the workspace" in caplog.text


def _workspace_with_submodule(base: Path, workspace_id: str, tmp_path: Path) -> Path:
    """`_workspace`, whose `app` has a pushed submodule at `lib`; returns `app`."""
    ws = _workspace(base, workspace_id, tmp_path)
    app = ws / "repos" / "app"
    library = tmp_path / f"{workspace_id}-library.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(library))
    seed = tmp_path / f"{workspace_id}-library-seed"
    _git(tmp_path, "clone", str(library), str(seed))
    (seed / "lib.txt").write_text("lib\n")
    _git(seed, "add", "lib.txt")
    _git(seed, "commit", "-m", "lib")
    _git(seed, "push", "origin", "HEAD:main")
    _git(app, "-c", "protocol.file.allow=always", "submodule", "add", str(library), "lib")
    _git(app, "commit", "-m", "add lib")
    _git(app, "push", "origin", "HEAD:main")
    return app


def _record_git_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[tuple[str, ...], dict[str, str]]]:
    """Every subprocess host git starts, as (argv, env); each still runs."""
    calls: list[tuple[tuple[str, ...], dict[str, str]]] = []
    real = asyncio.create_subprocess_exec

    async def recording(*argv: str, env: dict[str, str], **kwargs: object) -> object:
        calls.append((argv, env))
        return await real(*argv, env=env, **kwargs)

    monkeypatch.setattr(stale_dirs.asyncio, "create_subprocess_exec", recording)
    return calls


@pytest.mark.parametrize(
    ("key", "attributes"),
    [("filter.pc130.clean", "* filter=pc130\n"), ("core.fsmonitor", None)],
)
async def test_a_submodule_config_never_runs_through_its_superproject(
    base: Path,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    attributes: str | None,
) -> None:
    """The superproject's diff runs git inside the submodule, under the submodule's config."""
    app = _workspace_with_submodule(base, "ws-subconfig", tmp_path)
    lib = app / "lib"
    marker = tmp_path / "pwned"
    _git(lib, "config", key, f"touch {marker}; cat")
    if attributes is not None:
        (lib / ".gitattributes").write_text(attributes)
    # Same size, newer mtime: git has to hash the file, which runs a clean filter.
    later = time.time() + 60
    os.utime(lib / "lib.txt", (later, later))
    calls = _record_git_calls(monkeypatch)
    result = await _reclaimer(base).run_once()
    assert result.kept == ("ws-subconfig",)
    assert f"{lib} sets {key.lower()}, which is not on the host-git allowlist" in caplog.text
    assert not marker.exists()
    # Refused before any repository in the workspace was read, not after.
    assert {argv[argv.index("-C") + 2] for argv, _ in calls} == {"config"}


@pytest.mark.parametrize("holder", ["chained", "bare"])
async def test_alternates_leading_outside_at_any_depth_are_refused_and_kept(
    base: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture, holder: str
) -> None:
    """Git follows alternates of alternates: an intermediate that is no repository leads out too."""
    ws = _workspace(base, f"ws-{holder}", tmp_path)
    outside_objects = _outside_repo(tmp_path) / ".git" / "objects"
    if holder == "chained":
        repo = ws / "repos" / "app"
        plain = ws / "plain" / "objects"
        (plain / "info").mkdir(parents=True)
        (plain / "info" / "alternates").write_text(f"{outside_objects}\n")
        (repo / ".git" / "objects" / "info" / "alternates").write_text(
            "../../../../plain/objects\n"
        )
    else:
        repo = ws / "repos" / "mirror.git"
        _git(ws / "repos", "clone", "--bare", str(ws / "repos" / "app"), "mirror.git")
        (repo / "objects" / "info" / "alternates").write_text(f"{outside_objects}\n")
    result = await _reclaimer(base).run_once()
    assert result.kept == (f"ws-{holder}",)
    assert f"{repo} reads {outside_objects}, outside the workspace" in caplog.text


@pytest.mark.parametrize("shape", ["quoted", "too-deep"])
async def test_alternates_git_would_read_differently_are_refused_and_kept(
    base: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture, shape: str
) -> None:
    """A C-quoted entry is not parsed as a path, and a chain git stops following is not guessed at."""
    ws = _workspace(base, f"ws-{shape}", tmp_path)
    app = ws / "repos" / "app"
    alternates = app / ".git" / "objects" / "info" / "alternates"
    if shape == "quoted":
        alternates.write_text('"../../../../plain/objects"\n')
        expected = f"{app} has a quoted alternate"
    else:
        # Six plain object directories inside the workspace, each naming the next.
        for depth in range(6):
            info = ws / "plain" / str(depth) / "objects" / "info"
            info.mkdir(parents=True)
            if depth < 5:
                (info / "alternates").write_text(f"../../{depth + 1}/objects\n")
        alternates.write_text("../../../../plain/0/objects\n")
        expected = f"{app} chains alternates past 5"
    result = await _reclaimer(base).run_once()
    assert result.kept == (f"ws-{shape}",)
    assert expected in caplog.text


@pytest.mark.parametrize("library_named", [False, True])
async def test_a_workspace_with_a_submodule_store_is_kept_unproven(
    base: Path, tmp_path: Path, library_named: bool
) -> None:
    """Codex r2: `.git/modules` is never proven, even with the submodule's remote named."""
    app = _workspace_with_submodule(base, "ws-sub", tmp_path)
    assert (app / "lib" / ".git").is_file()
    library = str(tmp_path / "ws-sub-library.git")
    extra = (library,) if library_named else ()
    result = await _reclaimer(base, extra_remotes=extra).run_once()
    assert _reason(result, "ws-sub") is RetainedReason.SUBMODULE_STORE_UNPROVEN


async def test_every_host_git_call_runs_guarded(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hooks, fsmonitor, system and global config are off on every call, not on most."""
    _workspace(base, "ws-calls", tmp_path)
    bare = _workspace(base, "ws-calls-bare", tmp_path)
    _git(bare / "repos", "clone", "--bare", str(bare / "repos" / "app"), "mirror.git")
    calls = _record_git_calls(monkeypatch)
    result = await _reclaimer(base).run_once()
    assert result.reclaimed == ("ws-calls", "ws-calls-bare")
    in_repo = [
        (argv, env) for argv, env in calls if "-C" in argv and argv[argv.index("-C") + 1] != "/"
    ]
    subcommands = {argv[argv.index("-C") + 2] for argv, _ in in_repo}
    assert {
        "config",
        "for-each-ref",
        "diff",
        "ls-files",
        "rev-list",
        "cat-file",
        "fsck",
    } <= subcommands
    for argv, env in in_repo:
        assert argv[0] == "git"
        overrides = argv[1 : argv.index("-C")]
        if argv[argv.index("-C") + 2] == "config":
            # The listing passes trust only, so our overrides are not read back.
            assert overrides == ("-c", "safe.directory=*"), argv
        else:
            assert "core.hooksPath=/dev/null" in overrides, argv
            assert "core.fsmonitor=false" in overrides, argv
        if "diff" in argv:
            assert "--ignore-submodules=dirty" in argv, argv
        assert env["GIT_CONFIG_NOSYSTEM"] == "1", argv
        assert env["GIT_CONFIG_GLOBAL"] == "/dev/null", argv
        assert env["HOME"] == "/nonexistent", argv
        # Codex r1 finding 2: replacement refs never rewrite what an id means.
        assert env["GIT_NO_REPLACE_OBJECTS"] == "1", argv


# --- the delete path: off the loop, budgeted, resumable (#1983 field data) ---


def _many_files(ws: Path, count: int) -> None:
    """A tree of small files like a real workspace's node_modules, all pushed-clean."""
    cache = ws / "repos" / "app" / "target"
    cache.mkdir()
    (cache / "CACHEDIR.TAG").write_bytes(b"Signature: 8a477f597d28d172789f06886806bc55\n")
    for i in range(count):
        sub = cache / f"d{i % 10}"
        sub.mkdir(exist_ok=True)
        (sub / f"f{i}.o").write_bytes(b"x")
    (ws / "repos" / "app" / ".git" / "info" / "exclude").write_text("target/\n")


class _Ticks:
    """A monotonic clock that advances one second per read."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


async def test_a_delete_out_of_time_resumes_after_a_restart_without_a_second_judgment(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-big", tmp_path)
    _many_files(ws, 200)
    first = _reclaimer(base)
    ticks = _Ticks()
    first.monotonic = ticks
    first.pass_budget_seconds = 30.0

    from syn_adapters.workspace_backends.reclaim_delete import delete_tree_until

    def budgeted(path: str, identity: tuple[int, int], deadline: float) -> bool:
        return delete_tree_until(path, identity, deadline, ticks)

    first.delete_tree = budgeted
    result = await first.run_once()
    assert result.deleting == ("ws-big",)
    assert result.out_of_time
    assert result.reclaimed == ()
    [left] = [p for p in base.iterdir() if p.name != AUTH_DIRNAME]
    assert left.name == ".deleting-ws-big"  # never put back: it was proven
    assert any(left.rglob("*"))  # part of the tree is still there

    # A restart: a fresh reclaimer whose read models know nothing of the
    # first, and whose repositories are half gone. It finishes the delete.
    restarted = _reclaimer(base, known_owner=False)
    second = await restarted.run_once()
    assert second.reclaimed == ("ws-big",)
    assert list(base.iterdir()) == []


async def test_a_half_deleted_dir_a_container_binds_is_left(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-half", tmp_path)
    stat = ws.lstat()
    claimed = claim_workspace_dir(str(ws))
    deleting = Path(
        authorize_and_mark(claimed, "ws-half", (stat.st_dev, stat.st_ino), now=time.time())
    )
    bound = ContainerMounts("odd01", ("/srv/workspaces/.deleting-ws-half",))
    result = await _reclaimer(base, containers=[bound]).run_once()
    assert _reason(result, "ws-half") is RetainedReason.MOUNTED
    assert deleting.is_dir()


async def test_the_pass_budget_stops_before_the_next_directory(base: Path, tmp_path: Path) -> None:
    _workspace(base, "ws-one", tmp_path)
    _workspace(base, "ws-two", tmp_path)
    reclaimer = _reclaimer(base)
    reclaimer.pass_budget_seconds = 0.0
    result = await reclaimer.run_once()
    assert result.out_of_time
    assert result.reclaimed == ()
    assert sorted(p.name for p in base.iterdir()) == ["ws-one", "ws-two"]


async def test_the_delete_runs_off_the_event_loop(base: Path, tmp_path: Path) -> None:
    _workspace(base, "ws-thread", tmp_path)
    reclaimer = _reclaimer(base)
    loop_thread: list[bool] = []
    real = reclaimer.delete_tree

    def recording(path: str, identity: tuple[int, int], deadline: float) -> bool:
        try:
            asyncio.get_running_loop()
            loop_thread.append(True)
        except RuntimeError:
            loop_thread.append(False)
        return real(path, identity, deadline)

    reclaimer.delete_tree = recording
    result = await reclaimer.run_once()
    assert result.reclaimed == ("ws-thread",)
    assert loop_thread == [False]


def test_delete_tree_until_refuses_anything_not_marked_and_never_follows_links(
    tmp_path: Path,
) -> None:
    from syn_adapters.workspace_backends.reclaim_delete import delete_tree_until

    plain = tmp_path / "ws-plain"
    plain.mkdir()
    with pytest.raises(ValueError, match="not a directory marked"):
        delete_tree_until(str(plain), (0, 0), float("inf"), time.monotonic)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("not ours\n")
    marked = tmp_path / ".deleting-ws-x"
    (marked / "sub").mkdir(parents=True)
    (marked / "sub" / "link").symlink_to(outside, target_is_directory=True)
    (marked / "sub" / "f.txt").write_text("x\n")
    found = marked.lstat()
    identity = (found.st_dev, found.st_ino)
    assert delete_tree_until(str(marked), identity, float("inf"), time.monotonic) is True
    assert not marked.exists()
    assert (outside / "keep.txt").read_text() == "not ours\n"


# --- owner decision: run history is kept; only scratch dirs are deleted ---


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
async def test_a_failed_run_gets_no_extra_hold(base: Path, tmp_path: Path, status: str) -> None:
    """Terminal plus the settle period, whatever the outcome: debugging evidence
    lives in events and artifacts, not on the workspace disk."""
    _workspace(base, f"ws-{status}", tmp_path)
    result = await _reclaimer(base, status=status, ended_seconds_ago=_SETTLE + 1).run_once()
    assert result.reclaimed == (f"ws-{status}",)


async def test_nothing_outside_the_workspace_base_is_ever_deleted(
    base: Path, tmp_path: Path
) -> None:
    """Even a proven directory: a delete target that is not a direct child of the
    base (an event store, an artifact bucket, a transcript dir) is refused."""
    _workspace(base, "ws-escape", tmp_path)
    history = tmp_path / "run-history"
    (history / ".deleting-ws-escape").mkdir(parents=True)
    (history / ".deleting-ws-escape" / "events.log").write_text("every run, kept\n")
    reclaimer = _reclaimer(base)
    reclaimer.mark_deleting = lambda _claimed, _workspace_id, _identity: str(
        history / ".deleting-ws-escape"
    )
    result = await reclaimer.run_once()
    assert _reason(result, "ws-escape") is RetainedReason.DELETE_FAILED
    assert (history / ".deleting-ws-escape" / "events.log").read_text() == "every run, kept\n"
