"""An orphan kept at startup reaches the execution's stream, and never costs the keep (#2321).

Drives the consumer - the startup `_guard_orphaned_workspaces` - with the real
recorder over a stream stored as JSON. Only docker, the guard's walk and the
event store are doubles. The stale-directory reclaimer is deliberately not
wired: the janitor must never write the event store (#1983,
`test_deletion_primitives_are_confined`).
"""

from __future__ import annotations

import pytest

from syn_api.services import reconciliation
from syn_domain.contexts.orchestration import (
    OrphanedWorkspace,
    ReclaimableDir,
    Retained,
    RetainedReason,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_2321_workspace_retained_recorded import (
    EXECUTION,
    started_stream,
)

pytestmark = pytest.mark.unit


class _DownStore:
    async def get_by_id(self, execution_id: str, /) -> None:
        raise ConnectionError("event store down")

    async def save(self, aggregate: object) -> None:
        raise AssertionError("never reached")


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
