"""An orphaned workspace's directory is deleted only after the guard has cleared it (#1560).

The order is the whole point: deleting first would lose exactly the work that
``refs/syn/lost/...`` exists to keep. Every double here appends to one shared
log, so a deletion that happens before (or without) the guard's walk shows up
as a position in that log rather than as a missing call.

No real disk: the workspace is a scripted double and the remover only records.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow import orphaned_workspace
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    QuarantinedWork,
    SavedWork,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.orphaned_workspace import (
    OrphanedWorkspace,
    ReclaimableDir,
    guard_orphaned_workspace,
    remove_reclaimed_dir,
)

pytestmark = pytest.mark.unit


class _Workspace:
    """Answers the guard's walk: no repositories (clean), or cannot be reached."""

    def __init__(self, log: list[str], *, reachable: bool = True) -> None:
        self._log = log
        self._reachable = reachable

    async def execute(self, command: list[str]) -> ExecutionResult:
        self._log.append("guard")
        if not self._reachable:
            raise ConnectionError("container gone")
        return ExecutionResult(exit_code=0, success=True, duration_ms=1.0)

    async def renew_git_credential(self) -> object:
        return ()


class _Remover:
    def __init__(self, log: list[str]) -> None:
        self._log = log
        self.removed: list[str] = []

    def remove(self, host_dir: str) -> None:
        self._log.append("remove")
        self.removed.append(host_dir)


def _orphan(log: list[str], *, reachable: bool = True) -> OrphanedWorkspace:
    return OrphanedWorkspace(
        workspace=_Workspace(log, reachable=reachable),
        workspace_id="ws-1",
        execution_id="exec-1",
        host_dir="/workspaces/ws-1",
    )


async def _reclaim(orphan: OrphanedWorkspace, remover: _Remover) -> bool:
    reclaimable = await guard_orphaned_workspace(orphan)
    return reclaimable is not None and remove_reclaimed_dir(reclaimable, remover)


async def test_a_clean_orphan_is_deleted_and_only_after_the_guard_walked_it() -> None:
    log: list[str] = []
    remover = _Remover(log)

    assert await _reclaim(_orphan(log), remover)

    assert remover.removed == ["/workspaces/ws-1"]
    assert "guard" in log
    assert log.index("remove") > max(i for i, step in enumerate(log) if step == "guard")


async def test_an_orphan_the_guard_could_not_walk_is_kept() -> None:
    """Unreadable is not clean: these files may be the last copy."""
    log: list[str] = []
    remover = _Remover(log)

    assert not await _reclaim(_orphan(log, reachable=False), remover)

    assert remover.removed == []
    assert "remove" not in log


async def test_the_clearance_names_the_orphans_own_directory() -> None:
    reclaimable = await guard_orphaned_workspace(_orphan([]))
    assert reclaimable == ReclaimableDir(host_dir="/workspaces/ws-1", workspace_id="ws-1")


def test_the_quarantine_ref_stays_under_the_executions_namespace() -> None:
    assert _orphan([]).quarantine_phase == "orphaned-ws-1"


def _quarantined(*, landed: bool) -> QuarantinedWork:
    return QuarantinedWork(
        repo="/workspace/repos/app",
        branch="feature",
        commit_count=1,
        files=("a.py",),
        pushed_ref="refs/syn/lost/exec-1/orphaned-ws-1" if landed else None,
        push_error=None if landed else "403 forbidden",
    )


@pytest.mark.parametrize(("landed", "deleted"), [(True, True), (False, False)])
async def test_quarantined_work_is_deleted_only_once_its_push_landed(
    monkeypatch: pytest.MonkeyPatch, landed: bool, deleted: bool
) -> None:
    log: list[str] = []

    async def _saved(*_args: object, **_kwargs: object) -> SavedWork:
        log.append("guard")
        return SavedWork(quarantined=(_quarantined(landed=landed),))

    monkeypatch.setattr(orphaned_workspace, "save_unpushed_work", _saved)
    remover = _Remover(log)

    assert await _reclaim(_orphan(log), remover) is deleted
    assert log == (["guard", "remove"] if deleted else ["guard"])
