"""The Docker backend as a ``RunReaper`` (ADR-072 D3, D5, D6, D13; #1310 1.5).

Satisfies ``syn_adapters.execution_host.RunReaper``. Both selectors the
startup reap uses (workspace by name, legacy sidecar by component label) are
narrowed by ``syn.host_id`` and ``syn.execution_id``, so a live host's
containers, and the executor's containers for other runs, are never touched.
The unpushed-work guard (#1560) runs first, under the same narrowing.

Its Reap Scope is the engine it talks to: the ``docker info`` engine ID. A
reconciler only fences runs claimed against the same engine, because an empty
listing on any other engine shows nothing about them.
"""

from __future__ import annotations

import asyncio
import subprocess

from syn_adapters.workspace_backends.host_labels import LABEL_HOST_ID
from syn_api.services.reconciliation import (
    _docker_rm,
    _guard_orphaned_workspaces,
    _remove_reclaimed_dirs,
)
from syn_domain.contexts.orchestration.ports import IsolationLevel

LABEL_EXECUTION_ID = "syn.execution_id"

_SELECTORS = (
    ("label=syn.component=sidecar", "sidecar"),
    ("name=agentic-ws-", "workspace"),
)


class ReapScopeUnknown(RuntimeError):
    """The Docker engine ID could not be read, so this process cannot reconcile (D13)."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            f"Reap Scope unknown: {detail}. The executor refuses to start; check that "
            "this process can reach the Docker daemon (DOCKER_HOST, the mounted socket)."
        )


def _engine_id() -> str:
    """The ``docker info`` engine ID; raises rather than returning a scope that matches nothing."""
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ID}}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReapScopeUnknown(f"`docker info` could not run: {error}") from error
    engine_id = result.stdout.strip()
    if result.returncode != 0 or not engine_id:
        raise ReapScopeUnknown(
            f"`docker info` gave no engine ID (exit {result.returncode}): "
            f"{result.stderr.strip()[:500]}"
        )
    return engine_id


class DockerDeadHostReaper:
    """``reap`` is True only when every selector's removal is shown finished."""

    def __init__(self) -> None:
        self._scope: str | None = None

    def scope(self) -> str:
        """The engine ID, read once; never configured (D13)."""
        if self._scope is None:
            self._scope = _engine_id()
        return self._scope

    def provider(self) -> str:
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
