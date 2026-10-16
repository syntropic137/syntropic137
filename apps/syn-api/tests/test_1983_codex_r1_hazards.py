"""#1983 Codex round 1: each hazard reproduced for real, then shown to keep the work.

Real git repositories, a real bare remote, real file-system races. Where the
hazard depends on git behaving a certain way (a graft or a replacement ref
hiding a commit), the test first proves with plain git that the hazard is
real, so a pass here is not a near-miss.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from test_pc130_workspace_dir_reclaim import HOST_BASE, _git, _reason, _reclaimer, _workspace

from syn_adapters.workspace_backends import reclaim_delete
from syn_adapters.workspace_backends.orphaned import parse_inspect
from syn_adapters.workspace_backends.reclaim_delete import (
    AUTH_DIRNAME,
    authorize_and_mark,
    delete_tree_until,
)
from syn_adapters.workspace_backends.stale_dirs import ContainerMounts, claim_workspace_dir
from syn_domain.contexts.orchestration import RetainedReason

pytestmark = pytest.mark.unit


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "workspaces"
    path.mkdir()
    return path


def _out(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(app: Path, name: str) -> str:
    (app / name).write_text(f"{name}: the only copy\n")
    _git(app, "add", name)
    _git(app, "commit", "-m", name)
    return _out(app, "rev-parse", "HEAD")


# --- finding 1: reflog-only and unreachable work ---


async def test_work_reset_away_is_kept_while_the_reflog_holds_it(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-reset", tmp_path)
    app = ws / "repos" / "app"
    unpushed = _commit(app, "feature.py")
    _git(app, "reset", "--hard", "origin/main")
    assert _out(app, "status", "--porcelain") == ""  # clean, and every ref is pushed
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-reset") is RetainedReason.UNPUSHED_UNPROVEN
    assert _out(app, "cat-file", "-t", unpushed) == "commit"


async def test_an_amended_away_commit_is_kept(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-amend", tmp_path)
    app = ws / "repos" / "app"
    _commit(app, "draft.py")
    (app / "draft.py").write_text("second take\n")
    _git(app, "commit", "-a", "--amend", "-m", "amended")
    _git(app, "reset", "--hard", "origin/main")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-amend") is RetainedReason.UNPUSHED_UNPROVEN
    assert ws.exists()


async def test_a_deleted_branch_with_its_reflog_expired_is_kept(base: Path, tmp_path: Path) -> None:
    """No ref and no reflog reach it: only the object store (fsck) still does."""
    ws = _workspace(base, "ws-orphan-commit", tmp_path)
    app = ws / "repos" / "app"
    _git(app, "checkout", "-b", "scratch")
    lost = _commit(app, "experiment.py")
    _git(app, "checkout", "main")
    _git(app, "branch", "-D", "scratch")
    _git(app, "reflog", "expire", "--expire=now", "--all")
    assert lost not in _out(app, "log", "--all", "--reflog", "--format=%H")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-orphan-commit") is RetainedReason.UNREACHABLE_OBJECTS
    assert _out(app, "cat-file", "-t", lost) == "commit"


# --- finding 2: replacement refs and grafts rewrite ancestry ---


async def test_a_replacement_ref_cannot_fake_the_remote_proof(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-replace", tmp_path)
    app = ws / "repos" / "app"
    pushed = _out(app, "rev-parse", "origin/main")
    unpushed = _commit(app, "feature.py")
    # Make the advertised commit R read as a commit whose parent is U: then
    # ^R excludes U, and git counts nothing unpushed.
    child = _out(app, "commit-tree", f"{unpushed}^{{tree}}", "-p", unpushed, "-m", "cover")
    _git(app, "replace", pushed, child)
    # The hazard is real: with replacements honoured, git counts nothing unpushed.
    assert _out(app, "rev-list", "--count", unpushed, f"^{pushed}") == "0"
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-replace") is RetainedReason.UNPUSHED_UNPROVEN
    assert ws.exists()


async def test_a_graft_cannot_fake_the_remote_proof(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-graft", tmp_path)
    app = ws / "repos" / "app"
    pushed = _out(app, "rev-parse", "origin/main")
    unpushed = _commit(app, "feature.py")
    _git(app, "reset", "--hard", pushed)
    _git(app, "branch", "kept", unpushed)
    # Graft the pushed commit onto the unpushed one: now it "contains" it.
    (app / ".git" / "info" / "grafts").write_text(f"{pushed} {unpushed}\n")
    hazard = subprocess.run(
        ["git", "rev-list", "--count", unpushed, f"^{pushed}"],
        cwd=app,
        capture_output=True,
        text=True,
        check=False,
    )
    assert hazard.stdout.strip() == "0"
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-graft") is RetainedReason.UNPUSHED_UNPROVEN
    assert "grafts" in result.retained[0].detail


async def test_a_shallow_clone_with_an_unpushed_commit_is_kept(base: Path, tmp_path: Path) -> None:
    """A shallow boundary only removes parents: it cannot hide a tip."""
    _workspace(base, "ws-shallow-seed", tmp_path)
    remote = tmp_path / "ws-shallow-seed-remote.git"
    ws = base / "ws-shallow"
    (ws / "repos").mkdir(parents=True)
    _git(ws / "repos", "clone", "--depth", "1", f"file://{remote}", "app")
    app = ws / "repos" / "app"
    assert (app / ".git" / "shallow").exists()
    _commit(app, "feature.py")
    reclaimer = _reclaimer(base)
    named = (str(remote),)

    async def record(execution_id: str) -> object:
        from syn_domain.contexts.orchestration import OwnerExecution

        return OwnerExecution(execution_id, "completed", time.time() - 3600, named)

    reclaimer.execution_record = record  # type: ignore[assignment]
    result = await reclaimer.run_once()
    assert _reason(result, "ws-shallow") is RetainedReason.UNPUSHED_UNPROVEN


# --- finding 3: the deleting name alone authorizes nothing ---


async def test_a_forged_deleting_dir_with_no_authorization_is_kept(
    base: Path, tmp_path: Path
) -> None:
    forged = base / ".deleting-ws-forged"
    (forged / ".agentic-session-store").mkdir(parents=True)
    (forged / "only-copy.md").write_text("work nobody proved\n")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-forged") is RetainedReason.IDENTITY_CHANGED
    assert (forged / "only-copy.md").read_text() == "work nobody proved\n"


async def test_a_deleting_dir_replaced_after_its_authorization_is_kept(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-swapped-in", tmp_path)
    stat = ws.lstat()
    claimed = claim_workspace_dir(str(ws))
    deleting = Path(
        authorize_and_mark(claimed, "ws-swapped-in", (stat.st_dev, stat.st_ino), now=time.time())
    )
    deleting.rename(tmp_path / "the-authorized-one")
    deleting.mkdir()
    (deleting / "only-copy.md").write_text("another directory's work\n")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-swapped-in") is RetainedReason.IDENTITY_CHANGED
    assert (deleting / "only-copy.md").read_text() == "another directory's work\n"


async def test_a_mount_arriving_after_the_pass_snapshot_stops_the_resume(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-resumed", tmp_path)
    stat = ws.lstat()
    claimed = claim_workspace_dir(str(ws))
    deleting = Path(
        authorize_and_mark(claimed, "ws-resumed", (stat.st_dev, stat.st_ino), now=time.time())
    )
    reads: list[int] = []

    async def containers() -> list[ContainerMounts]:
        reads.append(1)
        if len(reads) == 1:
            return []  # the snapshot the pass opened with
        return [ContainerMounts("late0000001", (f"{HOST_BASE}/.deleting-ws-resumed",))]

    reclaimer = _reclaimer(base)
    reclaimer.list_containers = containers
    result = await reclaimer.run_once()
    assert _reason(result, "ws-resumed") is RetainedReason.MOUNTED
    assert (deleting / "repos" / "app" / "README.md").exists()


def test_the_authorization_lives_outside_every_workspace_and_is_never_listed(
    base: Path, tmp_path: Path
) -> None:
    from syn_adapters.workspace_backends.stale_dirs import scan_workspace_dirs

    ws = _workspace(base, "ws-auth", tmp_path)
    stat = ws.lstat()
    authorize_and_mark(claim_workspace_dir(str(ws)), "ws-auth", (stat.st_dev, stat.st_ino), now=1.0)
    record = json.loads((base / AUTH_DIRNAME / "ws-auth.json").read_text())
    assert (record["st_dev"], record["st_ino"]) == (stat.st_dev, stat.st_ino)
    assert [x.workspace_id for x in scan_workspace_dirs(str(base))] == ["ws-auth"]


# --- finding 4: a symlink swapped in during the delete ---


def test_a_directory_swapped_for_a_symlink_mid_delete_reaches_nothing_outside(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    precious = tmp_path / "history"
    precious.mkdir()
    (precious / "events.log").write_text("every run, kept\n")
    deleting = base / ".deleting-ws-race"
    (deleting / "sub").mkdir(parents=True)
    (deleting / "sub" / "a.o").write_text("scratch\n")
    found = deleting.lstat()
    real = reclaim_delete._scandir
    swapped: list[bool] = []

    def swap_after_listing(fd: int) -> object:
        entries = list(real(fd))
        if not swapped and any(e.name == "sub" for e in entries):
            # Enumerated as a directory; now it is a link to history.
            (deleting / "sub").rename(tmp_path / "moved-sub")
            (deleting / "sub").symlink_to(precious, target_is_directory=True)
            swapped.append(True)
        return iter(entries)

    monkeypatch.setattr(reclaim_delete, "_scandir", swap_after_listing)
    delete_tree_until(str(deleting), (found.st_dev, found.st_ino), float("inf"), time.monotonic)
    assert swapped == [True]
    assert (precious / "events.log").read_text() == "every run, kept\n"
    assert (tmp_path / "moved-sub" / "a.o").exists()


def test_a_tree_swapped_for_another_before_the_delete_is_refused(
    base: Path, tmp_path: Path
) -> None:
    deleting = base / ".deleting-ws-other"
    deleting.mkdir()
    found = deleting.lstat()
    deleting.rename(tmp_path / "authorized")
    deleting.mkdir()
    (deleting / "keep.md").write_text("not the authorized tree\n")
    with pytest.raises(OSError, match="not the authorized directory"):
        delete_tree_until(str(deleting), (found.st_dev, found.st_ino), float("inf"), time.monotonic)
    assert (deleting / "keep.md").exists()


# --- finding 6: content outside git metadata ---


async def test_an_authored_file_in_a_pushed_bare_clone_is_kept(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-bare-patch", tmp_path)
    _git(ws / "repos", "clone", "--bare", str(ws / "repos" / "app"), "mirror.git")
    (ws / "repos" / "mirror.git" / "recovery.patch").write_text("the only copy\n")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-bare-patch") is RetainedReason.UNVERSIONED
    assert "recovery.patch" in result.retained[0].detail


@pytest.mark.parametrize("name", ["notes.md", "MERGE_HEAD", "hooks/pre-commit"])
async def test_an_authored_file_inside_dot_git_is_kept(
    base: Path, tmp_path: Path, name: str
) -> None:
    ws = _workspace(base, "ws-dot-git", tmp_path)
    target = ws / "repos" / "app" / ".git" / name
    target.write_text("written by the agent\n")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-dot-git") is RetainedReason.UNVERSIONED
    assert target.exists()


# --- finding 7: maintenance arriving between the guard and the delete ---


async def test_maintenance_arriving_under_the_claim_puts_the_dir_back(
    base: Path, tmp_path: Path
) -> None:
    ws = _workspace(base, "ws-late-maint", tmp_path)
    reclaimer = _reclaimer(base)
    on = [False]

    async def maintenance() -> str | None:
        return "maintenance" if on[0] else None

    claim = reclaimer.claim

    def claim_then_maintenance(host_dir: str) -> str:
        claimed = claim(host_dir)
        on[0] = True
        return claimed

    reclaimer.paused = maintenance
    reclaimer.claim = claim_then_maintenance
    result = await reclaimer.run_once()
    assert result.paused == "maintenance"
    assert result.reclaimed == ()
    assert sorted(p.name for p in base.iterdir()) == ["ws-late-maint"]
    assert ws.exists()


# --- finding 8: a mount record docker gave us that we cannot read keeps everything ---


@pytest.mark.parametrize(
    "mount",
    [
        {"Destination": "/data"},
        {"Type": "bind", "Source": "", "Destination": "/data"},
        {"Type": "volume", "Source": 7, "Destination": "/data"},
        "not a mount",
    ],
)
def test_a_malformed_mount_makes_the_document_unreadable(mount: object) -> None:
    raw = json.dumps([{"State": {"Running": False}, "Mounts": [mount]}])
    assert parse_inspect(raw) is None


def test_a_tmpfs_mount_has_no_source_and_is_fine() -> None:
    raw = json.dumps([{"Mounts": [{"Type": "tmpfs", "Source": "", "Destination": "/tmp"}]}])
    inspected = parse_inspect(raw)
    assert inspected is not None
    assert inspected.mount_sources == ()


async def test_an_unreadable_container_skips_the_pass(
    base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from syn_adapters.workspace_backends import stale_dirs

    ws = _workspace(base, "ws-unreadable-mounts", tmp_path)

    class _Ps:
        returncode = 0

        async def communicate(self) -> tuple[bytes, None]:
            return b"cafe02\n", None

    async def ps(*_args: object, **_kwargs: object) -> _Ps:
        return _Ps()

    async def inspect(container_id: str) -> str:
        return json.dumps([{"Mounts": [{"Destination": "/workspace"}]}])

    monkeypatch.setattr(stale_dirs.asyncio, "create_subprocess_exec", ps)
    monkeypatch.setattr(stale_dirs, "docker_inspect_raw", inspect)
    reclaimer = _reclaimer(base)
    reclaimer.list_containers = stale_dirs.list_containers
    result = await reclaimer.run_once()
    assert result.skipped is not None
    assert ws.exists()


def test_os_supports_the_descriptor_relative_delete() -> None:
    assert os.open in os.supports_dir_fd
    assert os.unlink in os.supports_dir_fd
    assert os.rmdir in os.supports_dir_fd
    assert os.scandir in os.supports_fd


# --- Codex round 2 ---


async def test_content_staged_then_reset_away_is_kept_as_a_dangling_blob(
    base: Path, tmp_path: Path
) -> None:
    """`git add` wrote the only copy into the object store; the reset left it unreachable."""
    ws = _workspace(base, "ws-dangling-blob", tmp_path)
    app = ws / "repos" / "app"
    (app / "draft.txt").write_text("staged once, never committed\n")
    _git(app, "add", "draft.txt")
    blob = _out(app, "rev-parse", ":draft.txt")
    _git(app, "reset", "--hard", "origin/main")
    assert not (app / "draft.txt").exists()
    assert _out(app, "status", "--porcelain") == ""
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-dangling-blob") is RetainedReason.UNREACHABLE_OBJECTS
    assert _out(app, "cat-file", "-p", blob) == "staged once, never committed"


async def test_a_deinitialized_submodule_store_is_kept(base: Path, tmp_path: Path) -> None:
    """`submodule deinit` removes the checkout; its objects stay only in .git/modules."""
    from test_pc130_workspace_dir_reclaim import _workspace_with_submodule

    app = _workspace_with_submodule(base, "ws-deinit", tmp_path)
    lib_store = app / ".git" / "modules" / "lib"
    _git(app / "lib", "commit", "--allow-empty", "-m", "unpushed submodule work")
    _git(app, "submodule", "deinit", "-f", "lib")
    assert lib_store.is_dir()
    assert not any((app / "lib").iterdir())
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-deinit") is RetainedReason.SUBMODULE_STORE_UNPROVEN
    assert lib_store.is_dir()


async def test_a_bare_clone_with_a_submodule_store_is_kept(base: Path, tmp_path: Path) -> None:
    ws = _workspace(base, "ws-bare-modules", tmp_path)
    mirror = ws / "repos" / "mirror.git"
    _git(ws / "repos", "clone", "--bare", str(ws / "repos" / "app"), "mirror.git")
    (mirror / "modules").mkdir()
    _git(mirror / "modules", "init", "--bare", "lib")
    result = await _reclaimer(base).run_once()
    assert _reason(result, "ws-bare-modules") is RetainedReason.SUBMODULE_STORE_UNPROVEN
