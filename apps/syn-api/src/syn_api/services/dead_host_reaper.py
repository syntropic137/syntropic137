"""Reap the containers an executor left for one run (ADR-072 D3, D5, D6, D13; #1310 1.5).

Satisfies ``syn_adapters.execution_host.RunReaper``: the reconciler reaps a
dead executor's fenced run, and the host reaps its own finished run before it
frees the slot. Its scope is the local Docker engine's ID, read once at
startup, because the local daemon is all its ``docker`` calls can reach. Both selectors the
startup reap uses (workspace by name, legacy sidecar by component label) are
narrowed by ``syn.host_id`` and ``syn.execution_id``, so a live host's
containers, and the dead host's containers for other runs, are never touched.
The unpushed-work guard (#1560) runs first, under the same narrowing.
"""

from __future__ import annotations

import asyncio
import subprocess
from typing import TYPE_CHECKING

from syn_adapters.workspace_backends.host_labels import LABEL_HOST_ID
from syn_api.services.reconciliation import (
    _docker_rm,
    _guard_orphaned_workspaces,
    _remove_reclaimed_dirs,
)
from syn_domain.contexts.orchestration.ports import IsolationLevel

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.ports import ProviderId

LABEL_EXECUTION_ID = "syn.execution_id"

_SELECTORS = (
    ("label=syn.component=sidecar", "sidecar"),
    ("name=agentic-ws-", "workspace"),
)


class DockerEngineUnidentified(RuntimeError):
    """``docker info`` gave no engine ID, so this process cannot say what it can reap."""


class DockerDeadHostReaper:
    """``reap`` is True only when every selector's removal is shown finished."""

    def __init__(self, engine_id: str) -> None:
        if not engine_id.strip():
            raise DockerEngineUnidentified("docker info reported an empty engine ID")
        self._engine_id = engine_id.strip()

    @classmethod
    async def for_local_engine(cls) -> DockerDeadHostReaper:
        """Read the local daemon's engine ID; raises rather than guess a scope (D13)."""
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "info",
            "--format",
            "{{.ID}}",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            raise DockerEngineUnidentified(
                f"docker info exited {proc.returncode}: {stderr.decode(errors='replace')[:300]}"
            )
        return cls(stdout.decode())

    def scope(self) -> str:
        return self._engine_id

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
