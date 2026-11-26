"""#2221 option (a): an unowned workspace dir holding no repository, old enough, is reclaimed.

Opt-in (``SYN_DISK_RECLAIM_UNOWNED_REPO_FREE_AFTER_DAYS``). The git guards
can never pass a directory no execution owns - the unpushed guard trusts only
remotes the owner names - so the rule asks for no repository at all instead.
Age comes from the listing taken before the claim: birth time, else ctime,
never mtime. Every doubt keeps the directory, retained as ``unowned``.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest

from syn_adapters.workspace_backends import stale_dirs
from syn_adapters.workspace_backends.remote_refs import GitLsRemote
from syn_adapters.workspace_backends.stale_dirs import (
    ContainerMounts,
    SubprocessHostWorkspaceGit,
    WorkspaceDirListing,
    repository_doubt,
    scan_workspace_dirs,
)
from syn_api.services.workspace_dir_reclaim import ReclaimPass, WorkspaceDirReclaimer
from syn_domain.contexts.orchestration import OwnerExecution, RetainedReason
from syn_shared.settings.disk import DiskSettings

pytestmark = pytest.mark.unit

_DAY = 86400.0
_AFTER_DAYS = 7


def _reclaimer(
    base: Path,
    *,
    owners: set[str] | None = None,
    after_days: int | None = _AFTER_DAYS,
    days_from_now: float = 30.0,
) -> WorkspaceDirReclaimer:
    """Nothing binds anything; the pass's clock is ``days_from_now`` ahead of the real one."""

    async def list_containers() -> list[ContainerMounts]:
        return []

    async def workspace_owners(workspace_id: str) -> set[str]:
        return set() if owners is None else owners

    async def execution_record(execution_id: str) -> OwnerExecution | None:
        return None

    async def capture_unproven(execution_id: str) -> str | None:
        return None

    now = time.time() + days_from_now * _DAY
    return WorkspaceDirReclaimer(
        base_dir=str(base),
        settle_seconds=600.0,
        list_containers=list_containers,
        workspace_owners=workspace_owners,
        execution_record=execution_record,
        capture_unproven=capture_unproven,
        scan_dirs=scan_workspace_dirs,
        git=SubprocessHostWorkspaceGit(),
        remotes=GitLsRemote(),
        host_base_dir="/srv/workspaces",
        own_container="api0000000001",
        clock=lambda: now,
        unowned_repo_free_after_seconds=None if after_days is None else after_days * _DAY,
    )


def _repo_free(base: Path, workspace_id: str) -> Path:
    """A workspace dir with scratch files at some depth and no repository anywhere."""
    ws = base / workspace_id
    deep = ws / "repos" / "app" / "src"
    deep.mkdir(parents=True)
    (deep / "main.py").write_text("print('scratch')\n")
    (ws / "notes.txt").write_text("left behind\n")
    return ws


def _kept(result: ReclaimPass, workspace_id: str) -> tuple[RetainedReason, str]:
    [kept] = [r for r in result.retained if r.workspace_id == workspace_id]
    return kept.reason, kept.detail


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "workspaces"
    path.mkdir()
    return path


# --- reclaimed ---


async def test_a_repo_free_unowned_dir_old_enough_is_reclaimed(base: Path) -> None:
    ws = _repo_free(base, "ws-scratch")
    result = await _reclaimer(base).run_once()
    assert result.reclaimed == ("ws-scratch",)
    assert result.reclaimed_bytes > 0
    assert not ws.exists()
    assert list(base.iterdir()) == []  # Deleted, not merely claimed.


async def test_dry_run_only_reports_a_repo_free_unowned_dir(base: Path) -> None:
    ws = _repo_free(base, "ws-dry")
    reclaimer = _reclaimer(base)
    reclaimer.dry_run = True
    result = await reclaimer.run_once()
    assert result.would_reclaim == ("ws-dry",)
    assert ws.exists()


# --- a repository of any kind keeps it ---


async def test_a_git_directory_at_depth_keeps_it(base: Path) -> None:
    ws = _repo_free(base, "ws-deep")
    _git(ws / "repos" / "app", "init", "-q", "nested")
    result = await _reclaimer(base).run_once()
    reason, detail = _kept(result, "ws-deep")
    assert reason is RetainedReason.UNOWNED
    assert "a repository is at" in detail
    assert ws.exists()


async def test_a_gitfile_keeps_it(base: Path) -> None:
    ws = _repo_free(base, "ws-gitfile")
    (ws / "repos" / "app" / ".git").write_text("gitdir: /nowhere/at/all\n")
    result = await _reclaimer(base).run_once()
    assert _kept(result, "ws-gitfile")[0] is RetainedReason.UNOWNED
    assert ws.exists()


async def test_a_linked_worktree_keeps_it(base: Path, tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _git(origin, "commit", "-q", "--allow-empty", "-m", "seed")
    ws = _repo_free(base, "ws-worktree")
    _git(origin, "worktree", "add", "-q", str(ws / "tree"), "-b", "side")
    assert (ws / "tree" / ".git").is_file()
    result = await _reclaimer(base).run_once()
    assert _kept(result, "ws-worktree")[0] is RetainedReason.UNOWNED
    assert ws.exists()


async def test_a_bare_repository_keeps_it(base: Path) -> None:
    ws = _repo_free(base, "ws-bare")
    _git(ws, "init", "-q", "--bare", "mirror.git")
    result = await _reclaimer(base).run_once()
    reason, detail = _kept(result, "ws-bare")
    assert reason is RetainedReason.UNOWNED
    assert "a bare repository is at" in detail
    assert ws.exists()


async def test_a_bare_repository_shape_alone_keeps_it(base: Path) -> None:
    """HEAD beside objects/ and refs/ is a repository, whoever made it."""
    ws = _repo_free(base, "ws-shape")
    store = ws / "cache" / "anything"
    (store / "objects").mkdir(parents=True)
    (store / "refs").mkdir()
    (store / "HEAD").write_text("ref: refs/heads/main\n")
    result = await _reclaimer(base).run_once()
    assert _kept(result, "ws-shape")[0] is RetainedReason.UNOWNED
    assert ws.exists()


# --- age, setting, owners ---


async def test_a_dir_younger_than_the_setting_is_kept(base: Path) -> None:
    ws = _repo_free(base, "ws-young")
    result = await _reclaimer(base, days_from_now=_AFTER_DAYS - 1).run_once()
    reason, detail = _kept(result, "ws-young")
    assert reason is RetainedReason.UNOWNED
    assert f"under the {_AFTER_DAYS} days set" in detail
    assert ws.exists()


async def test_a_new_dir_with_an_old_mtime_is_still_young(base: Path) -> None:
    """Age is never mtime: an mtime is the agent's to set."""
    ws = _repo_free(base, "ws-backdated")
    month_ago = time.time() - 30 * _DAY
    os.utime(ws, (month_ago, month_ago))
    result = await _reclaimer(base, days_from_now=0.0).run_once()
    assert _kept(result, "ws-backdated")[0] is RetainedReason.UNOWNED
    assert ws.exists()


async def test_unset_keeps_every_unowned_dir_as_today(base: Path) -> None:
    ws = _repo_free(base, "ws-off")
    result = await _reclaimer(base, after_days=None).run_once()
    assert _kept(result, "ws-off") == (RetainedReason.UNOWNED, "no execution own it")
    assert ws.exists()


async def test_several_owners_keep_it(base: Path) -> None:
    ws = _repo_free(base, "ws-two")
    result = await _reclaimer(base, owners={"exec-a", "exec-b"}).run_once()
    assert _kept(result, "ws-two") == (RetainedReason.UNOWNED, "2 executions own it")
    assert ws.exists()


async def test_an_unknown_age_keeps_it(base: Path) -> None:
    ws = _repo_free(base, "ws-ageless")
    reclaimer = _reclaimer(base)

    def ageless(at: str) -> list[WorkspaceDirListing]:
        return [replace(x, created_at=None) for x in scan_workspace_dirs(at)]

    reclaimer.scan_dirs = ageless
    result = await reclaimer.run_once()
    assert _kept(result, "ws-ageless") == (
        RetainedReason.UNOWNED,
        "no execution owns it and its age is unknown",
    )
    assert ws.exists()


async def test_age_is_the_one_listed_before_the_claim(base: Path) -> None:
    """The claim renames the directory, which resets its ctime; that must not make it young.

    The first listing says a month old; every listing of the claimed name
    says what the rename made it, now. Judged from the rescan it would be kept.
    """
    ws = _repo_free(base, "ws-renamed")
    reclaimer = _reclaimer(base, days_from_now=0.0)
    month_ago = time.time() - 30 * _DAY

    def listed(at: str) -> list[WorkspaceDirListing]:
        return [
            x
            if Path(x.host_dir).name.startswith(stale_dirs.CLAIM_PREFIX)
            else replace(x, created_at=month_ago)
            for x in scan_workspace_dirs(at)
        ]

    reclaimer.scan_dirs = listed
    result = await reclaimer.run_once()
    assert result.reclaimed == ("ws-renamed",)
    assert not ws.exists()


async def test_a_repository_made_under_the_claim_keeps_it(base: Path) -> None:
    ws = _repo_free(base, "ws-late")
    reclaimer = _reclaimer(base)

    def claim_then_clone(host_dir: str) -> str:
        claimed = stale_dirs.claim_workspace_dir(host_dir)
        (Path(claimed) / "late" / ".git").mkdir(parents=True)
        return claimed

    reclaimer.claim = claim_then_clone
    result = await reclaimer.run_once()
    reason, detail = _kept(result, "ws-late")
    assert reason is RetainedReason.UNOWNED
    assert "a repository is at" in detail
    assert (ws / "late" / ".git").is_dir()  # Put back where it was found.


async def test_a_walk_past_its_budget_keeps_it(base: Path) -> None:
    ws = _repo_free(base, "ws-big")
    for n in range(20):
        (ws / f"f{n}").write_text("x")
    reclaimer = _reclaimer(base)
    reclaimer.repository_doubt = lambda at: repository_doubt(at, max_entries=10)
    result = await reclaimer.run_once()
    reason, detail = _kept(result, "ws-big")
    assert reason is RetainedReason.UNOWNED
    assert "more than 10 entries" in detail
    assert ws.exists()


# --- the probe itself ---


def test_an_unwalkable_dir_is_doubt(tmp_path: Path) -> None:
    doubt = repository_doubt(str(tmp_path / "gone"))
    assert doubt is not None
    assert "could not be walked" in doubt


def test_a_git_link_is_doubt_without_being_followed(tmp_path: Path) -> None:
    (tmp_path / ".git").symlink_to(tmp_path / "nowhere")
    assert repository_doubt(str(tmp_path)) == f"a repository is at {tmp_path}"


def test_a_repo_free_tree_is_no_doubt(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "HEAD").write_text("not a repository on its own\n")
    assert repository_doubt(str(tmp_path)) is None


def test_the_listing_ages_a_dir_by_ctime_not_mtime(tmp_path: Path) -> None:
    ws = tmp_path / "ws-aged"
    ws.mkdir()
    os.utime(ws, (1.0, 1.0))
    listing = stale_dirs.measure_workspace_dir(ws)
    assert listing.created_at == ws.lstat().st_ctime
    assert listing.created_at != 1.0


# --- the setting ---


def test_the_setting_is_unset_by_default() -> None:
    disk = DiskSettings(_env_file=None)  # type: ignore[call-arg]
    assert disk.reclaim_unowned_repo_free_after_days is None
    assert disk.unowned_repo_free_after_seconds() is None


def test_the_production_reclaimer_reads_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    from syn_api.services.workspace_dir_reclaim import default_reclaimer

    monkeypatch.setenv("SYN_DISK_RECLAIM_UNOWNED_REPO_FREE_AFTER_DAYS", "9")
    assert default_reclaimer(lambda: True).unowned_repo_free_after_seconds == 9 * _DAY


def test_zero_days_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYN_DISK_RECLAIM_UNOWNED_REPO_FREE_AFTER_DAYS", "0")
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        DiskSettings(_env_file=None)  # type: ignore[call-arg]
