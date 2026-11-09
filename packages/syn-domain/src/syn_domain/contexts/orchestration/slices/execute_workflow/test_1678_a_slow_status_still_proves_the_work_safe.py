"""A `git status` that is slow but finishing is an answer, not a reason to keep (#1678).

THE INCIDENT. On `flywheel` fourteen orphaned workspace directories sat on the
host because the guard's `git status` ran under the shared 30s local bound,
and the first walk of a large worktree in a fresh container did not finish in
it. The guard read that, correctly, as "could not prove the work safe" and kept
the directory - every time, for every such execution.

These run REAL git against REAL repositories, through the orphan path the
incident took (`guard_orphaned_workspace`), and assert against what that path
decides and what reached the origin. Only the clock is faked: `_SlowStatus`
answers a status the way coreutils `timeout` would if the walk took
``seconds`` - cut off with exit 124 when the bound in the argv is shorter,
otherwise the real answer. A real slow repository would make each test cost
minutes and prove nothing more.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow import workspace_git
from syn_domain.contexts.orchestration.slices.execute_workflow.orphaned_workspace import (
    OrphanedWorkspace,
    ReclaimableDir,
    guard_orphaned_workspace,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_unpushed_work_guard import (
    _EXECUTION_ID,
    _Clone,
    _clone_repository,
    _unbounded,
)

if TYPE_CHECKING:
    from pathlib import Path

    from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_git import (
        GitWorkspace,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

#: What the guard's status ran under before #1678, and what it timed out
#: against on `flywheel`. Written out rather than read from `workspace_git`,
#: because the point of the fixture is a walk the OLD bound could not hold.
_OLD_BOUND_SECONDS = 30

#: A cold walk longer than the old bound: the incident's case.
_COLD_WALK_SECONDS = _OLD_BOUND_SECONDS * 2

_WORKSPACE_ID = "ws-dd3bede5"
_HOST_DIR = f"/workspaces/{_WORKSPACE_ID}"


class _SlowStatus:
    """The real workspace, except every `git status` takes ``seconds`` to walk.

    Judged against the bound the argv itself carries (`timeout --kill-after=<k>
    <bound> ...`), so what decides the outcome is the number the guard chose,
    read at the port - not a value the test handed it. Found as an argv token
    rather than by `_operation`, because `moved_gitlinks` puts `-c` pairs
    between `-C <repo>` and `status`.
    """

    def __init__(self, inner: GitWorkspace, *, seconds: int) -> None:
        self._inner = inner
        self._seconds = seconds
        self.bounds: list[int] = []

    async def renew_git_credential(self) -> object:
        return await self._inner.renew_git_credential()

    async def execute(self, command: list[str]) -> ExecutionResult:
        if "status" not in _unbounded(command):
            return await self._inner.execute(command)
        assert command[0] == "timeout", f"a status reached the port unbounded: {command}"
        bound = int(command[2])
        self.bounds.append(bound)
        if bound < self._seconds:
            return ExecutionResult(
                exit_code=workspace_git.BOUND_FIRED_EXIT_CODE,
                success=False,
                duration_ms=bound * 1000.0,
                stdout="",
                stderr="",
            )
        return await self._inner.execute(command)


def _orphan(workspace: GitWorkspace) -> OrphanedWorkspace:
    return OrphanedWorkspace(
        workspace=workspace,
        workspace_id=_WORKSPACE_ID,
        execution_id=_EXECUTION_ID,
        host_dir=_HOST_DIR,
    )


@pytest.fixture
def clone(tmp_path: Path) -> _Clone:
    return _clone_repository(tmp_path)


async def test_a_status_slower_than_the_old_bound_still_proves_a_pushed_tree_safe(
    clone: _Clone,
) -> None:
    """The incident's case: nothing at risk, a status that needed a minute."""
    clone.commit("shipped.py", "work that reached the remote\n")
    clone.git("push", "origin", "HEAD")
    workspace = _SlowStatus(clone.workspace, seconds=_COLD_WALK_SECONDS)

    reclaimable = await guard_orphaned_workspace(_orphan(workspace))

    assert reclaimable == ReclaimableDir(host_dir=_HOST_DIR, workspace_id=_WORKSPACE_ID), (
        f"a {_COLD_WALK_SECONDS}s status was cut off under bounds {workspace.bounds}, so a "
        "tree whose every commit is on the remote was kept on the host anyway"
    )


#: The backend's default execute timeout, which is what "no bound" costs here
#: (#1231). Larger must still mean bounded well short of it.
_BACKEND_DEFAULT_SECONDS = 3600


@pytest.mark.parametrize(
    ("seconds", "reclaimed"),
    [
        (workspace_git.STATUS_TIMEOUT_SECONDS, True),
        (workspace_git.STATUS_TIMEOUT_SECONDS + 1, False),
        (_BACKEND_DEFAULT_SECONDS, False),
    ],
    ids=[
        "exactly-the-bound-finishes",
        "one-second-over-keeps-the-directory",
        "an-hour-keeps-the-directory",
    ],
)
async def test_the_status_bound_is_still_a_bound_and_still_says_so(
    clone: _Clone, caplog: pytest.LogCaptureFixture, seconds: int, reclaimed: bool
) -> None:
    """Larger is not unbounded: past it the directory is kept, with the same message.

    The first two pin where the line is: a walk exactly as long as the bound is
    answered, one second longer is a command cut off, named as such, and a
    directory that stays - "any doubt keeps the directory" is unchanged. The
    third pins that the line exists at all: a status that would run for the
    backend's hour is still cut off by this bound, not by that one.
    """
    workspace = _SlowStatus(clone.workspace, seconds=seconds)

    with caplog.at_level(logging.INFO):
        reclaimable = await guard_orphaned_workspace(_orphan(workspace))

    assert (reclaimable is not None) is reclaimed
    if reclaimed:
        return
    kept = [r.getMessage() for r in caplog.records if "Keeping orphaned workspace" in r.message]
    assert kept, f"a directory was kept without saying so: {caplog.text}"
    assert _HOST_DIR in kept[0]
    assert "running 'git status' in" in kept[0], (
        f"the message does not name the command that did not finish: {kept[0]}"
    )
    assert "status --porcelain" in kept[0], kept[0]
    assert "timed out, so it did not finish" in kept[0], kept[0]


async def test_modified_and_untracked_files_are_still_work_under_a_slow_status(
    clone: _Clone,
) -> None:
    """The larger bound buys time, not leniency: what the walk finds is still work.

    Both statuses on this path are slow here - the v1 listing and the v2 one
    `moved_gitlinks` asks once anything is dirty - so a hop left on the old
    bound fails this as surely as the first one would. The proof is the
    origin: the edit and the new file are in the quarantine commit.
    """
    (clone.path / "README.md").write_text("an edit nobody committed\n")
    (clone.path / "notes.md").write_text("a file nobody added\n")
    workspace = _SlowStatus(clone.workspace, seconds=_COLD_WALK_SECONDS)

    reclaimable = await guard_orphaned_workspace(_orphan(workspace))

    ref = f"refs/syn/lost/{_EXECUTION_ID}/orphaned-{_WORKSPACE_ID}"
    assert ref in clone.origin_refs(), (
        f"uncommitted work was not quarantined under a {_COLD_WALK_SECONDS}s status "
        f"(bounds {workspace.bounds}); origin has {sorted(clone.origin_refs())}"
    )
    assert clone.origin_git("show", f"{ref}:README.md") == "an edit nobody committed"
    assert clone.origin_git("show", f"{ref}:notes.md") == "a file nobody added"
    assert len(workspace.bounds) >= 2, (
        f"expected the v1 and v2 statuses both to run, saw bounds {workspace.bounds}"
    )
    # Quarantined and landed, so only now is the directory reclaimable.
    assert reclaimable is not None
