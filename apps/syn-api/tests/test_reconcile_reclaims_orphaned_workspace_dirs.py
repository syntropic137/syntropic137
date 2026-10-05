"""Startup reconciliation guards orphaned workspaces, reaps them, THEN deletes their dirs (#1560).

The order is the guarantee: the guard runs inside the orphan's container, so
it must run before the reap; the directory may hold the last copy of its work,
so it must not be deleted before the guard cleared it. Every step appends to
one log, and the assertion is on positions in that log.

No docker and no disk: every hop is replaced by a recording double.
"""

from __future__ import annotations

import pytest

from syn_api.services import reconciliation
from syn_domain.contexts.orchestration import OrphanedWorkspace, ReclaimableDir

pytestmark = pytest.mark.unit


def _patch(monkeypatch: pytest.MonkeyPatch, log: list[str], *, reap_fails: bool) -> None:
    async def _ps(_filter: str) -> list[str]:
        return ["c1"]

    async def _find(ids: list[str]) -> list[OrphanedWorkspace]:
        return [
            OrphanedWorkspace(
                workspace=object(),  # type: ignore[arg-type]  # never executed: the guard is replaced
                workspace_id="ws-1",
                execution_id="exec-1",
                host_dir="/workspaces/ws-1",
            )
            for _ in ids
        ]

    async def _guard(orphan: OrphanedWorkspace) -> ReclaimableDir:
        log.append("guard")
        return ReclaimableDir(host_dir=orphan.host_dir, workspace_id=orphan.workspace_id)

    async def _rm(_selector: str, label: str) -> str | None:
        log.append(f"reap:{label}")
        return f"{label}: failed" if reap_fails else None

    class _Remover:
        def remove(self, host_dir: str) -> None:
            log.append(f"remove:{host_dir}")

    monkeypatch.setattr(reconciliation, "_docker_ps_ids", _ps)
    monkeypatch.setattr(reconciliation, "_docker_rm", _rm)
    monkeypatch.setattr("syn_adapters.workspace_backends.orphaned.find_orphaned_workspaces", _find)
    monkeypatch.setattr(
        "syn_adapters.workspace_backends.orphaned.ShutilWorkspaceDirRemover", _Remover
    )
    monkeypatch.setattr("syn_domain.contexts.orchestration.guard_orphaned_workspace", _guard)


async def test_guard_then_reap_then_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _patch(monkeypatch, log, reap_fails=False)

    result = await reconciliation.cleanup_orphaned_containers()

    assert result.fully_reaped
    assert log == ["guard", "reap:sidecar", "reap:workspace", "remove:/workspaces/ws-1"]


async def test_an_unfinished_reap_deletes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A container that may still be running may still be writing to its directory."""
    log: list[str] = []
    _patch(monkeypatch, log, reap_fails=True)

    result = await reconciliation.cleanup_orphaned_containers()

    assert not result.fully_reaped
    assert not any(step.startswith("remove:") for step in log)
