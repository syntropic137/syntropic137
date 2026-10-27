"""How much workspace memory one process has handed out, so a big workspace counts as more (okrs-51p.30).

The execution budget counts RUNS: at most N at once, whatever each one holds.
That was exact while every workspace had the same memory limit. Once a phase
can ask for 16 GB, a run is no longer one unit of host: four 16 GB builds
admitted as four runs would hold what sixteen default runs were sized for, and
the kernel settles the difference by OOM-killing someone.

So workspaces also draw from this ledger, sized in MB:

    capacity = SYN_EXECUTION_MAX_CONCURRENT x SYN_WORKSPACE_MEMORY_LIMIT_MB

which is the memory the operator already sized the host for (the budget's own
description says to check host RAM covers that many workspaces). A default
workspace draws exactly one budget slot's share, so with no phase requesting
anything this ledger never makes anyone wait that the budget would not. A
16 GB phase on a 4 GB default draws four shares and waits until they are free.

Ceilings, not measurements. ``host_capacity`` sizes the budget from what runs
measurably USED, and that is right for runs nobody has said anything about. A
request is the author saying this phase will use more than the profile shows,
so what it reserves is what it asked for.

FIFO with no barging, like ``ExecutionBudget``: a small workspace never slips
past a large one that is waiting, or a stream of small ones would starve it.
A request larger than the whole capacity is granted when nothing else holds
memory, so it runs alone rather than never.

Per process and not durable, for the same reason as the budget: what it holds
is the workspaces alive in THIS process, which a restart loses along with them.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class _Waiter:
    memory_mb: int
    granted: asyncio.Future[None] = field(repr=False)


class MemoryReservation:
    """One workspace's share of the ledger. ``release`` is idempotent."""

    def __init__(self, ledger: WorkspaceMemoryLedger, memory_mb: int) -> None:
        self._ledger = ledger
        self.memory_mb = memory_mb
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._ledger._give_back(self.memory_mb)


class WorkspaceMemoryLedger:
    """At most ``capacity_mb`` of workspace memory is reserved at once; the rest wait in order."""

    def __init__(self, capacity_mb: int) -> None:
        if capacity_mb < 1:
            msg = f"A workspace memory ledger needs a capacity of at least 1 MB, not {capacity_mb}"
            raise ValueError(msg)
        self._capacity_mb = capacity_mb
        self._reserved_mb = 0
        self._holders = 0
        self._waiting: list[_Waiter] = []

    @property
    def capacity_mb(self) -> int:
        return self._capacity_mb

    @property
    def reserved_mb(self) -> int:
        """Memory held by live workspaces."""
        return self._reserved_mb

    @property
    def waiting(self) -> int:
        """Workspaces queued for memory."""
        return len(self._waiting)

    async def reserve(self, memory_mb: int, *, workspace_id: str) -> MemoryReservation:
        """Wait for ``memory_mb`` to be free, then hold it until the reservation is released.

        Cancellation while waiting gives the place back; cancellation after the
        grant but before this returns gives the memory back.
        """
        waiter = _Waiter(memory_mb, asyncio.get_running_loop().create_future())
        self._waiting.append(waiter)
        self._grant()
        if not waiter.granted.done():
            logger.info(
                "Workspace %s waits for %d MB of workspace memory: %d of %d MB reserved, %d ahead",
                workspace_id,
                memory_mb,
                self._reserved_mb,
                self._capacity_mb,
                len(self._waiting) - 1,
            )
        try:
            await waiter.granted
        except BaseException:
            if waiter in self._waiting:
                self._waiting.remove(waiter)
                self._grant()
            elif waiter.granted.done() and not waiter.granted.cancelled():
                self._give_back(memory_mb)
            raise
        return MemoryReservation(self, memory_mb)

    def _fits(self, memory_mb: int) -> bool:
        return self._holders == 0 or self._reserved_mb + memory_mb <= self._capacity_mb

    def _grant(self) -> None:
        """Hand memory to waiters in arrival order, stopping at the first that does not fit."""
        while self._waiting:
            head = self._waiting[0]
            if head.granted.done():
                # Cancelled while queued, and its task has not run its cleanup
                # yet. It holds no memory and must not be given any.
                self._waiting.pop(0)
                continue
            if not self._fits(head.memory_mb):
                return
            self._waiting.pop(0)
            self._reserved_mb += head.memory_mb
            self._holders += 1
            head.granted.set_result(None)

    def _give_back(self, memory_mb: int) -> None:
        self._reserved_mb -= memory_mb
        self._holders -= 1
        self._grant()


def ledger_capacity_mb(max_concurrent: int, default_memory_mb: int) -> int:
    """The memory one process may hand to workspaces: its run budget at the default size."""
    return max_concurrent * default_memory_mb
