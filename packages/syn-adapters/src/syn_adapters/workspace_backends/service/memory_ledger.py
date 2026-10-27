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

RELEASED ONLY WHEN THE CONTAINER IS SHOWN GONE. A clean teardown of a named
container is that proof, and releases at once. Anything else LEAKS the
reservation instead: it stays charged, logged at ERROR, until the
``WorkspaceMemoryReconciler`` settles it. That covers a teardown that failed
or was interrupted, a create that raised (a backend may have made the
container and failed to remove it), and a create that was cancelled (the
``docker run`` it started carries on). The reconciler is the ONE path that
settles a leak, with the Run Queue on or off: it frees a workspace's memory
only when no container labelled with its ``syn.workspace_id`` is listed AND
no create for it is in flight. Holding memory for a container that may be
dead is the conservative failure; freeing memory a live container still uses
is the over-commit this module exists to prevent.
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


class LedgerReservation:
    """One workspace's share of the ledger. ``release`` and ``leak`` are idempotent, and final."""

    def __init__(self, ledger: WorkspaceMemoryLedger, memory_mb: int, workspace_id: str) -> None:
        self._ledger = ledger
        self.memory_mb = memory_mb
        self.workspace_id = workspace_id
        self._settled = False

    def release(self) -> None:
        """The container is shown gone: give its memory back."""
        if self._settled:
            return
        self._settled = True
        self._ledger._give_back(self.memory_mb)

    def leak(self, execution_id: str, *, reason: str) -> None:
        """The container may still exist: keep its memory charged until the reconciler shows it gone."""
        if self._settled:
            return
        self._settled = True
        self._ledger._hold_leaked(self.workspace_id, self.memory_mb)
        logger.error(
            "Workspace %s of %s may still exist (%s); its %d MB stay charged until no "
            "container of it is listed. %d MB of %d are held for possibly-live containers.",
            self.workspace_id,
            execution_id,
            reason,
            self.memory_mb,
            self._ledger.leaked_mb,
            self._ledger.capacity_mb,
        )

    def create_started(self) -> None:
        """A create for this workspace is running: no listing can show it gone until it ends."""
        self._ledger._creating.add(self.workspace_id)

    def create_ended(self) -> None:
        """The create, and any removal of what it made, has finished."""
        self._ledger._creating.discard(self.workspace_id)


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
        #: workspace id -> MB held for a container that may still exist.
        self._leaked: dict[str, int] = {}
        #: Workspaces whose create has started and not yet ended.
        self._creating: set[str] = set()

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

    @property
    def leaked_mb(self) -> int:
        """Memory held for containers not yet shown gone."""
        return sum(self._leaked.values())

    def leaked(self) -> frozenset[str]:
        """The workspaces whose memory waits on the reconciler."""
        return frozenset(self._leaked)

    def creating(self) -> frozenset[str]:
        """The workspaces with a create in flight."""
        return frozenset(self._creating)

    def settle_absent(
        self,
        listed: frozenset[str],
        *,
        leaked_before: frozenset[str],
        creating_before: frozenset[str],
    ) -> int:
        """Free each leak whose container is shown gone. Returns the MB freed.

        ``listed`` is every workspace id a listing found a container for;
        ``leaked_before`` and ``creating_before`` are the leaks and the creates
        in flight when that listing STARTED. Only a leak that already existed
        then can be judged: one whose create began and ended during the listing
        may own a container the listing never saw (Codex on #2148). A leak is
        settled only when it was leaked before, is not listed, was not being
        created before, and has no create in flight now.
        """
        settled = [
            workspace_id
            for workspace_id in self._leaked
            if workspace_id in leaked_before
            and workspace_id not in listed
            and workspace_id not in creating_before
            and workspace_id not in self._creating
        ]
        freed = 0
        for workspace_id in settled:
            memory_mb = self._leaked.pop(workspace_id)
            freed += memory_mb
            self._give_back(memory_mb)
            logger.warning(
                "No container of workspace %s is listed: its %d MB are returned",
                workspace_id,
                memory_mb,
            )
        return freed

    def _hold_leaked(self, workspace_id: str, memory_mb: int) -> None:
        self._leaked[workspace_id] = memory_mb

    async def reserve(self, memory_mb: int, *, workspace_id: str) -> LedgerReservation:
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
        return LedgerReservation(self, memory_mb, workspace_id)

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
