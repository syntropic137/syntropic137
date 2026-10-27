"""Settles leaked workspace memory once its container is shown gone (okrs-51p.30, #2148).

A reservation the workspace service could not prove free stays charged in the
``WorkspaceMemoryLedger`` (see ``memory_ledger``). This is the one path that
frees it while the process lives, with the Run Queue on or off: on a clock,
list every container that carries a ``syn.workspace_id`` label, and settle a
leak only when its workspace is not listed AND no create for it was in flight
when the listing started or is now.

The listing is the proof, so a listing that fails settles nothing. The
in-flight half covers a create the caller abandoned: the ``docker run`` it
started may land a container after the listing was read.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.memory_ledger import WorkspaceMemoryLedger

logger = logging.getLogger(__name__)

#: How often leaks are checked. A tick with nothing leaked lists nothing.
MEMORY_RECONCILE_INTERVAL_SECONDS = 30.0

#: The label every workspace container, and its sidecar, carries.
LABEL_WORKSPACE_ID = "syn.workspace_id"

#: ``docker ps`` may not take longer than this; a slower one settles nothing.
_LIST_TIMEOUT_SECONDS = 10.0


class WorkspacePresence(Protocol):
    """Which workspaces still have a container, in any state."""

    async def listed(self) -> frozenset[str]:
        """Every ``syn.workspace_id`` a container carries. Raises when it cannot list."""
        ...


class DockerWorkspacePresence:
    """``WorkspacePresence`` over ``docker ps -a``: a stopped container still counts."""

    async def listed(self) -> frozenset[str]:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "ps",
            "-a",
            "--filter",
            f"label={LABEL_WORKSPACE_ID}",
            "--format",
            f'{{{{.Label "{LABEL_WORKSPACE_ID}"}}}}',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_LIST_TIMEOUT_SECONDS
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise
        if proc.returncode != 0:
            msg = f"docker ps exited {proc.returncode}: {stderr.decode(errors='replace').strip()}"
            raise RuntimeError(msg)
        return frozenset(line.strip() for line in stdout.decode().splitlines() if line.strip())


class WorkspaceMemoryReconciler:
    """Frees each leaked reservation whose container a listing shows gone."""

    def __init__(self, ledger: WorkspaceMemoryLedger, presence: WorkspacePresence) -> None:
        self._ledger = ledger
        self._presence = presence

    async def run_once(self) -> int | None:
        """Settle what can be shown gone; the MB freed, or None when the listing failed.

        Never raises. A failed listing is not "0 MB freed": nothing was decided.
        """
        # Read BEFORE listing: a create that ends during the listing may have
        # made a container the listing did not see, and a leak recorded during
        # it may be that create's.
        leaked_before = self._ledger.leaked()
        if not leaked_before:
            return 0
        creating_before = self._ledger.creating()
        try:
            listed = await self._presence.listed()
        except Exception:
            logger.warning(
                "Could not list workspace containers; %d MB of leaked workspace memory stay "
                "charged until a listing succeeds",
                self._ledger.leaked_mb,
                exc_info=True,
            )
            return None
        return self._ledger.settle_absent(
            listed, leaked_before=leaked_before, creating_before=creating_before
        )

    async def run_on_a_clock(self, interval_seconds: float) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(interval_seconds)
