"""Reap the containers a dead executor left for one fenced run (ADR-072 D5, D6; #1310 1.5).

Satisfies ``syn_adapters.execution_host.DeadHostReaper``. Both selectors the
startup reap uses (workspace by name, legacy sidecar by component label) are
narrowed by ``syn.host_id`` and ``syn.execution_id``, so a live host's
containers, and the dead host's containers for other runs, are never touched.
The unpushed-work guard (#1560) runs first, under the same narrowing.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from syn_adapters.workspace_backends.host_labels import LABEL_HOST_ID
from syn_api.services.reconciliation import (
    _docker_rm,
    _guard_orphaned_workspaces,
    _remove_reclaimed_dirs,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.ports import FencedRun

LABEL_EXECUTION_ID = "syn.execution_id"

_SELECTORS = (
    ("label=syn.component=sidecar", "sidecar"),
    ("name=agentic-ws-", "workspace"),
)


class DockerDeadHostReaper:
    """``reap`` is True only when every selector's removal is shown finished."""

    async def reap(self, run: FencedRun) -> bool:
        owned = (
            f"label={LABEL_HOST_ID}={run.executor_id}",
            f"label={LABEL_EXECUTION_ID}={run.execution_id}",
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
