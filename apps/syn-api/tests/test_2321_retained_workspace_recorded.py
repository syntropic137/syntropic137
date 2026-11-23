"""Each keep for unproven work reaches the execution's stream, and never costs the keep (#2321).

Drives the consumers - `WorkspaceDirReclaimer.run_once` and the startup
`_guard_orphaned_workspaces` - with the real domain guards and the real
recorder over a stream stored as JSON. Only git, docker and the event store
are doubles.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_adapters.workspace_backends.stale_dirs import scan_workspace_dirs
from syn_api.services import reconciliation
from syn_api.services.workspace_dir_reclaim import WorkspaceDirReclaimer
from syn_domain.contexts.orchestration import (
    OrphanedWorkspace,
    OwnerExecution,
    ReclaimableDir,
    Retained,
    RetainedReason,
    RetainedWorkspaceRecorder,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_2321_workspace_retained_recorded import (
    EXECUTION,
    started_stream,
)

if TYPE_CHECKING:
    from pathlib import Path

    from syn_adapters.workspace_backends.stale_dirs import ContainerMounts

pytestmark = pytest.mark.unit

HOST_BASE = "/srv/workspaces"


class _Git:
    """Host git that answers every proof but the one ``reason`` names."""

    def __init__(self, reason: RetainedReason) -> None:
        self._reason = reason

    async def repositories(self, host_dir: str) -> list[str]:
        if self._reason is RetainedReason.UNREADABLE:
            raise PermissionError(f"{host_dir}/repos/app/.git")
        return [f"{host_dir}/repos/app"]

    async def has_stash(self, repo: str) -> bool:
        return self._reason is RetainedReason.STASH

    async def is_dirty(self, repo: str) -> bool:
        return self._reason is RetainedReason.DIRTY

    async def unversioned_paths(self, host_dir: str, repos: list[str]) -> list[str]:
        return ["notes.txt"] if self._reason is RetainedReason.UNVERSIONED else []

    async def has_submodule_store(self, repo: str) -> bool:
        return self._reason is RetainedReason.SUBMODULE_STORE_UNPROVEN

    async def unreachable_objects(self, repo: str) -> int:
        return 3 if self._reason is RetainedReason.UNREACHABLE_OBJECTS else 0

    async def unproven_commits(self, repo: str, advertised: frozenset[str]) -> int:
        return 2 if self._reason is RetainedReason.UNPUSHED_UNPROVEN else 0


class _Remote:
    async def advertised(self, url: str) -> frozenset[str]:
        return frozenset({"abc"})


def _reclaimer(
    base: Path, reason: RetainedReason, recorder: RetainedWorkspaceRecorder
) -> WorkspaceDirReclaimer:
    async def no_containers() -> list[ContainerMounts]:
        return []

    async def owners(workspace_id: str) -> set[str]:
        return {EXECUTION}

    async def record(execution_id: str) -> OwnerExecution:
        return OwnerExecution(
            execution_id, "cancelled", terminal_at=0.0, repositories=("https://x/app.git",)
        )

    async def captured(execution_id: str) -> str | None:
        return None

    return WorkspaceDirReclaimer(
        base_dir=str(base),
        settle_seconds=60.0,
        list_containers=no_containers,
        workspace_owners=owners,
        execution_record=record,
        capture_unproven=captured,
        scan_dirs=scan_workspace_dirs,
        git=_Git(reason),
        remotes=_Remote(),
        host_base_dir=HOST_BASE,
        recorder=recorder,
    )


#: Every reason `guard_stale_workspace_dir` keeps an owned directory for.
_STALE_KEEPS = [
    RetainedReason.STASH,
    RetainedReason.DIRTY,
    RetainedReason.UNREADABLE,
    RetainedReason.UNVERSIONED,
    RetainedReason.SUBMODULE_STORE_UNPROVEN,
    RetainedReason.UNREACHABLE_OBJECTS,
    RetainedReason.UNPUSHED_UNPROVEN,
]


@pytest.mark.parametrize("reason", _STALE_KEEPS, ids=lambda r: r.value)
async def test_each_stale_keep_records_one_event_however_many_passes_keep_it(
    tmp_path: Path, reason: RetainedReason
) -> None:
    (tmp_path / "ws-build" / "repos" / "app").mkdir(parents=True)
    stream = await started_stream(cancelled=True)
    reclaimer = _reclaimer(tmp_path, reason, RetainedWorkspaceRecorder(lambda: stream))

    first = await reclaimer.run_once()
    await reclaimer.run_once()

    assert [r.reason for r in first.retained] == [reason]
    assert (tmp_path / "ws-build").is_dir()
    [event] = stream.retained()
    assert (event.workspace_handle, event.phase_id, event.reason) == ("ws-build", "build", reason)


class _DownStore:
    async def get_by_id(self, execution_id: str, /) -> None:
        raise ConnectionError("event store down")

    async def save(self, aggregate: object) -> None:
        raise AssertionError("never reached")


async def test_a_stale_keep_whose_record_fails_still_keeps_the_directory(
    tmp_path: Path,
) -> None:
    (tmp_path / "ws-build" / "repos" / "app").mkdir(parents=True)
    recorder = RetainedWorkspaceRecorder(lambda: _DownStore())  # type: ignore[arg-type, return-value]

    result = await _reclaimer(tmp_path, RetainedReason.DIRTY, recorder).run_once()

    assert [r.reason for r in result.retained] == [RetainedReason.DIRTY]
    assert result.reclaimed == ()
    assert (tmp_path / "ws-build").is_dir()


# --- the startup guard over orphaned containers ---


def _patch_orphans(monkeypatch: pytest.MonkeyPatch, stream: object) -> None:
    async def _ps(_filter: str, *narrower: str) -> list[str]:
        return ["kept", "clean"]

    async def _find(ids: list[str]) -> list[OrphanedWorkspace]:
        return [
            OrphanedWorkspace(
                workspace=object(),  # type: ignore[arg-type]  # never executed: the guard is replaced
                workspace_id="ws-build" if c == "kept" else "ws-clean",
                execution_id=EXECUTION,
                host_dir=f"/workspaces/{c}",
            )
            for c in ids
        ]

    async def _guard(orphan: OrphanedWorkspace) -> ReclaimableDir | Retained:
        if orphan.workspace_id == "ws-build":
            return Retained(RetainedReason.UNPUSHED_UNPROVEN, "A quarantine push was refused.")
        return ReclaimableDir(host_dir=orphan.host_dir, workspace_id=orphan.workspace_id)

    monkeypatch.setattr(reconciliation, "_docker_ps_ids", _ps)
    monkeypatch.setattr("syn_adapters.workspace_backends.orphaned.find_orphaned_workspaces", _find)
    monkeypatch.setattr("syn_domain.contexts.orchestration.guard_orphaned_workspace", _guard)
    monkeypatch.setattr(
        "syn_adapters.storage.repositories.get_workflow_execution_repository", lambda: stream
    )


async def test_an_orphan_kept_at_startup_is_recorded_and_only_the_clean_one_is_cleared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = await started_stream()
    _patch_orphans(monkeypatch, stream)

    cleared = await reconciliation._guard_orphaned_workspaces()

    assert cleared is not None
    assert [d.workspace_id for d in cleared] == ["ws-clean"]
    [event] = stream.retained()
    assert (event.workspace_handle, event.phase_id, event.reason) == (
        "ws-build",
        "build",
        RetainedReason.UNPUSHED_UNPROVEN,
    )


async def test_an_orphan_whose_record_fails_is_still_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_orphans(monkeypatch, _DownStore())

    cleared = await reconciliation._guard_orphaned_workspaces()

    assert cleared is not None
    assert [d.workspace_id for d in cleared] == ["ws-clean"]

