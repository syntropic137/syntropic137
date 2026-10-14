"""Containers that carry no ``syn.host_id`` (ADR-072 D6; #1310 1.5).

A container created before the host labels shipped cannot be attributed to an
executor, so no host-scoped reap ever selects it. It is reaped only when no
executor other than this one has a live heartbeat: then nobody else can own it.
Otherwise it is logged and left, because it may be a live host's running work.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from syn_adapters.workspace_backends.host_labels import LABEL_HOST_ID
from syn_api.services.reconciliation import _guard_orphaned_workspaces, _remove_reclaimed_dirs

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.ports import ExecutionRunQueue

logger = logging.getLogger(__name__)

_SELECTORS = ("label=syn.component=sidecar", "name=agentic-ws-")
_DOCKER_TIMEOUT_S = 10


async def reap_unlabelled_if_alone(queue: ExecutionRunQueue, host_id: str) -> None:
    """Remove unlabelled agent containers only if ``host_id`` is the only live executor."""
    unlabelled = await _unlabelled_ids()
    if not unlabelled:
        return
    if await queue.others_live(host_id):
        logger.warning(
            "Left %d unlabelled container(s) %s: another executor is live, so they "
            "may be its work (ADR-072 D6)",
            len(unlabelled),
            ", ".join(unlabelled),
        )
        return
    logger.info("Reaping unlabelled container(s) %s: no other executor is live", unlabelled)
    # BEFORE the removal (#1560), narrowed to exactly these containers.
    reclaimable = await _guard_orphaned_workspaces(*(f"id={c}" for c in unlabelled))
    removed = await _docker("rm", "-f", *unlabelled)
    if reclaimable is not None and removed is not None:
        await asyncio.to_thread(_remove_reclaimed_dirs, reclaimable)


async def _unlabelled_ids() -> list[str]:
    ids: list[str] = []
    for selector in _SELECTORS:
        listing = await _docker(
            "ps",
            "-a",
            "--filter",
            selector,
            "--format",
            f'{{{{.ID}}}} {{{{.Label "{LABEL_HOST_ID}"}}}}',
        )
        for line in (listing or "").splitlines():
            container_id, _, owner = line.partition(" ")
            if container_id and not owner.strip() and container_id not in ids:
                ids.append(container_id)
    return ids


async def _docker(*args: str) -> str | None:
    """Run one docker command; None (logged) when it could not be shown to succeed."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        logger.warning("`docker %s` could not start", args[0], exc_info=True)
        return None
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_DOCKER_TIMEOUT_S)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        logger.warning("`docker %s` timed out", args[0])
        return None
    if proc.returncode != 0:
        logger.warning("`docker %s` exited %s", args[0], proc.returncode)
        return None
    return stdout.decode()
