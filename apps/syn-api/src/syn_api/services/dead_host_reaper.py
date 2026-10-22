"""Reap the containers an executor left for one run (ADR-072 D3, D5, D6; #1310 1.5).

Satisfies ``syn_adapters.execution_host.RunReaper``: the host calls it before
closing its own run, and a reconciler before releasing a fenced one. Its scope
is this daemon's engine ID, so only runs claimed on this daemon are fenced
here. Both selectors the
startup reap uses (workspace by name, legacy sidecar by component label) are
narrowed by ``syn.host_id`` and ``syn.execution_id``, so a live host's
containers, and the dead host's containers for other runs, are never touched.
The unpushed-work guard (#1560) runs first, under the same narrowing.
"""

from __future__ import annotations

import asyncio
import subprocess
from functools import cache

from syn_adapters.workspace_backends.host_labels import LABEL_HOST_ID
from syn_api.services.reconciliation import (
    _docker_rm,
    _guard_orphaned_workspaces,
    _remove_reclaimed_dirs,
)
from syn_domain.contexts.orchestration.ports import IsolationLevel, ProviderId

LABEL_EXECUTION_ID = "syn.execution_id"

_SELECTORS = (
    ("label=syn.component=sidecar", "sidecar"),
    ("name=agentic-ws-", "workspace"),
)


_DOCKER_INFO_TIMEOUT_S = 30


@cache
def _engine_id() -> str:
    """This daemon's engine ID; read once, because it is the scope a budget row records."""
    engine_id = subprocess.run(
        ["docker", "info", "--format", "{{.ID}}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=_DOCKER_INFO_TIMEOUT_S,
    ).stdout.strip()
    if not engine_id:
        raise RuntimeError(
            "docker info returned no engine ID; this executor's reap scope is unknown"
        )
    return engine_id


class DockerDeadHostReaper:
    """``reap`` is True only when every selector's removal is shown finished."""

    def scope(self) -> str:
        return _engine_id()

    def provider(self) -> ProviderId:
        return "docker"

    def isolation(self) -> IsolationLevel:
        return IsolationLevel.CONTAINER

    async def reap(self, executor_id: str, execution_id: str) -> bool:
        owned = (
            f"label={LABEL_HOST_ID}={executor_id}",
            f"label={LABEL_EXECUTION_ID}={execution_id}",
        )
        # BEFORE the reap (#1560), and only in this run's own workspaces: the
        # guard runs inside the orphan, the last moment its work can be saved.
        reclaimable = await _guard_orphaned_workspaces(*owned)
        failures = [
            failure
            for selector, kind in _SELECTORS
            if (failure := await _docker_rm(selector, kind, *owned)) is not None
        ]
        if reclaimable is not None and not failures:
            await asyncio.to_thread(_remove_reclaimed_dirs, reclaimable)
        return not failures
