"""A host-scoped reap still guards unpushed work before removal (#1560, ADR-072 D6; R2).

The flag-ON startup skips the global cleanup, so the dead-host reap and the
unlabelled reap are the only places an orphan's unpushed work can still be
quarantined. A fake docker holds A's orphan and B's live workspace and applies
the filters it is given; every hop appends to one log, asserted by position.
"""

from __future__ import annotations

import pytest

from syn_api.services import dead_host_reaper, reconciliation, unlabelled_containers
from syn_domain.contexts.orchestration import OrphanedWorkspace, ReclaimableDir
from syn_domain.contexts.orchestration.ports import FencedRun

pytestmark = pytest.mark.unit

_CONTAINERS = {
    "ws-a": {"name=agentic-ws-", "label=syn.host_id=host-a", "label=syn.execution_id=exec-a"},
    "ws-b": {"name=agentic-ws-", "label=syn.host_id=host-b", "label=syn.execution_id=exec-b"},
    "ws-old": {"name=agentic-ws-"},
}


def _matching(*filters: str) -> list[str]:
    ids = [f.removeprefix("id=") for f in filters if f.startswith("id=")]
    rest = {f for f in filters if not f.startswith("id=")}
    return [c for c, tags in _CONTAINERS.items() if rest <= tags and (not ids or c in ids)]


def _patch(monkeypatch: pytest.MonkeyPatch, log: list[str]) -> None:
    async def _ps(filter_arg: str, *narrower: str) -> list[str]:
        return _matching(filter_arg, *narrower)

    async def _find(ids: list[str]) -> list[OrphanedWorkspace]:
        return [
            OrphanedWorkspace(
                workspace=object(),  # type: ignore[arg-type]  # never executed: the guard is replaced
                workspace_id=c,
                execution_id=c,
                host_dir=f"/workspaces/{c}",
            )
            for c in ids
        ]

    async def _guard(orphan: OrphanedWorkspace) -> ReclaimableDir:
        log.append(f"guard:{orphan.workspace_id}")
        return ReclaimableDir(host_dir=orphan.host_dir, workspace_id=orphan.workspace_id)

    async def _rm(selector: str, label: str, *narrower: str) -> str | None:
        log.extend(f"rm:{c}" for c in _matching(selector, *narrower))
        return None

    class _Remover:
        def remove(self, host_dir: str) -> None:
            log.append(f"remove:{host_dir}")

    monkeypatch.setattr(reconciliation, "_docker_ps_ids", _ps)
    monkeypatch.setattr(dead_host_reaper, "_docker_rm", _rm)
    monkeypatch.setattr("syn_adapters.workspace_backends.orphaned.find_orphaned_workspaces", _find)
    monkeypatch.setattr(
        "syn_adapters.workspace_backends.orphaned.ShutilWorkspaceDirRemover", _Remover
    )
    monkeypatch.setattr("syn_domain.contexts.orchestration.guard_orphaned_workspace", _guard)


async def test_the_dead_hosts_orphan_is_guarded_before_removal_and_b_is_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log: list[str] = []
    _patch(monkeypatch, log)
    run = FencedRun(execution_id="exec-a", executor_id="host-a", reconciler="host-b", token=2)

    assert (
        await dead_host_reaper.DockerDeadHostReaper().reap(run.executor_id, run.execution_id)
        is True
    )

    assert log == ["guard:ws-a", "rm:ws-a", "remove:/workspaces/ws-a"]


class _Queue:
    def __init__(self, *, others: bool) -> None:
        self.others = others

    async def others_live(self, host_id: str) -> bool:
        return self.others


async def test_an_unlabelled_orphan_is_guarded_before_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log: list[str] = []
    _patch(monkeypatch, log)

    async def _unlabelled() -> list[str]:
        return ["ws-old"]

    async def _docker(*args: str) -> str | None:
        log.append(" ".join(args))
        return ""

    monkeypatch.setattr(unlabelled_containers, "_unlabelled_ids", _unlabelled)
    monkeypatch.setattr(unlabelled_containers, "_docker", _docker)

    await unlabelled_containers.reap_unlabelled_if_alone(_Queue(others=False), "host-b")  # type: ignore[arg-type]  # only others_live is read

    assert log == ["guard:ws-old", "rm -f ws-old", "remove:/workspaces/ws-old"]
