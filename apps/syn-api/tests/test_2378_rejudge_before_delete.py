"""#2378: a ``.deleting-`` directory is judged again in full right before its delete.

The hazard: work that appears after a directory was proven, authorized and
marked. Nothing judged between the mark and the delete, and a resumed delete
judged the contents not at all. Real git, a real bare remote and the real
guard, as in the PC-130 suite; the unpushed commit is made at the
``.deleting-`` path itself, so only a judgment there can see it.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from test_pc130_workspace_dir_reclaim import _git, _reason, _reclaimer, _workspace

from syn_adapters.workspace_backends.reclaim_delete import (
    AUTH_DIRNAME,
    authorize_and_mark,
    authorized_identity,
)
from syn_adapters.workspace_backends.stale_dirs import claim_workspace_dir
from syn_domain.contexts.orchestration import RetainedReason

if TYPE_CHECKING:
    from syn_api.services.workspace_dir_reclaim import WorkspaceDirReclaimer

pytestmark = pytest.mark.unit


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "workspaces"
    path.mkdir()
    return path


def _commit(repo: Path, name: str) -> None:
    (repo / name).write_text("work nobody has pushed\n")
    _git(repo, "add", name)
    _git(repo, "commit", "-m", name)


def _marked_by_a_dead_pass(ws: Path) -> Path:
    """A ``.deleting-`` directory with a valid authorization, as a restart finds it."""
    found = ws.lstat()
    claimed = claim_workspace_dir(str(ws))
    return Path(authorize_and_mark(claimed, ws.name, (found.st_dev, found.st_ino), now=time.time()))


def _commits_after_the_mark(reclaimer: WorkspaceDirReclaimer, marked: list[Path]) -> None:
    """Mark for real, then commit inside the marked directory before anything else runs."""
    real = reclaimer.mark_deleting

    def mark_then_commit(claimed: str, workspace_id: str, identity: tuple[int, int]) -> str:
        at = real(claimed, workspace_id, identity)
        _commit(Path(at) / "repos" / "app", "late.txt")
        marked.append(Path(at))
        return at

    reclaimer.mark_deleting = mark_then_commit


async def test_a_commit_made_after_the_mark_keeps_the_dir_and_revokes_its_authorization(
    base: Path, tmp_path: Path
) -> None:
    _workspace(base, "ws-late", tmp_path)
    first = _reclaimer(base)
    marked: list[Path] = []
    _commits_after_the_mark(first, marked)

    result = await first.run_once()

    assert result.reclaimed == ()
    assert _reason(result, "ws-late") is RetainedReason.UNPUSHED_UNPROVEN
    [at] = marked
    assert (at / "repos" / "app" / "late.txt").read_text() == "work nobody has pushed\n"
    assert authorized_identity(str(at)) is None

    # Even once the work is pushed, no later pass finishes a delete it revoked.
    _git(at / "repos" / "app", "push", "origin", "HEAD:main")
    later = await _reclaimer(base).run_once()
    assert later.reclaimed == ()
    assert _reason(later, "ws-late") is RetainedReason.IDENTITY_CHANGED
    assert (at / "repos" / "app" / "late.txt").exists()


async def test_a_resumed_delete_whose_repo_is_now_unpushed_is_kept(
    base: Path, tmp_path: Path
) -> None:
    at = _marked_by_a_dead_pass(_workspace(base, "ws-resumed", tmp_path))
    _commit(at / "repos" / "app", "late.txt")

    result = await _reclaimer(base).run_once()

    assert result.reclaimed == ()
    assert _reason(result, "ws-resumed") is RetainedReason.UNPUSHED_UNPROVEN
    assert (at / "repos" / "app" / "late.txt").exists()
    assert authorized_identity(str(at)) is None


async def test_nothing_changed_after_the_mark_is_still_deleted(base: Path, tmp_path: Path) -> None:
    _workspace(base, "ws-quiet", tmp_path)
    reclaimer = _reclaimer(base)
    real = reclaimer.mark_deleting
    marked: list[str] = []

    def mark(claimed: str, workspace_id: str, identity: tuple[int, int]) -> str:
        marked.append(real(claimed, workspace_id, identity))
        return marked[-1]

    reclaimer.mark_deleting = mark
    result = await reclaimer.run_once()

    assert result.reclaimed == ("ws-quiet",)
    assert [Path(m).name for m in marked] == [".deleting-ws-quiet"]
    assert list(base.iterdir()) == []


async def test_an_unchanged_resumed_delete_is_still_finished(base: Path, tmp_path: Path) -> None:
    at = _marked_by_a_dead_pass(_workspace(base, "ws-left", tmp_path))
    assert sorted(p.name for p in base.iterdir()) == [at.name, AUTH_DIRNAME]

    result = await _reclaimer(base).run_once()

    assert result.reclaimed == ("ws-left",)
    assert list(base.iterdir()) == []
