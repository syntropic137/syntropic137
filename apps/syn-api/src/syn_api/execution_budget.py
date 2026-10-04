"""One execution concurrency budget for every start path (#1557).

Before this, three paths started executions and only two were limited, by a
semaphore named for one of them: `SYN_POLLING_MAX_CONCURRENT_DISPATCHES` (default
1) bounded trigger dispatch AND resume starts, while `POST /execute` ran
unbounded beside them. So after an incident, five resumes waited an hour each
behind one running resumed child, invisible as `dispatched`, while direct runs
went straight past.

This is the one object every path now claims a slot from. It is per process,
like the API that hosts the executions, and it is not durable on purpose: what
it holds is "which starts are waiting in THIS process", which a restart loses
along with the tasks themselves. The durable record of what is owed a start is
each path's own to-do list (the resume start list, the trigger dispatch
records), and those re-offer after a restart.

A claim is taken SYNCHRONOUSLY, in the same step that creates the start task.
That is what makes it usable as a duplicate check: between "is this start
already here" and "it is here now" nothing can interleave.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class StartPath(StrEnum):
    """Which entrance an execution start came through."""

    DIRECT = "direct"
    """`POST /workflows/{id}/execute`."""
    TRIGGER = "trigger"
    """A trigger rule's dispatch, through `BackgroundWorkflowDispatcher.run_workflow`."""
    RESUME = "resume"
    """The child of an admitted resume, through `ResumeStartProcessManager`."""


class StartAlreadyClaimedError(Exception):
    """This execution already holds a claim in this process: queued or running."""

    def __init__(self, execution_id: str) -> None:
        super().__init__(f"The start of {execution_id} is already queued or running here")
        self.execution_id = execution_id


@dataclass(frozen=True)
class StartClaim:
    """One execution's place in the budget, from the moment its start is accepted."""

    execution_id: str
    workflow_id: str
    path: StartPath
    claimed_at: datetime
    resumed_from: str | None = None
    """The parent's id, for a resume start. The resume to-do list is keyed by it."""


@dataclass(frozen=True)
class StartPosition:
    """Where one claimed start stands right now."""

    claim: StartClaim
    position: int | None
    """1 is next to start. None once the start holds a slot."""
    running: int
    """Starts holding a slot, this one included if it holds one."""
    waiting: int
    """Starts queued behind the limit."""
    limit: int

    @property
    def queued(self) -> bool:
        return self.position is not None


@dataclass
class _Entry:
    claim: StartClaim
    granted: asyncio.Future[None] = field(repr=False)


class ExecutionBudget:
    """At most ``limit`` executions hold a slot; the rest wait, first come first served.

    A hand-off rather than a semaphore: a released slot is given to the oldest
    waiter directly, so a newcomer can never barge past the queue, and a
    waiter's position is a fact this object can report rather than a guess.
    """

    def __init__(self, limit: int) -> None:
        if limit < 1:
            msg = f"An execution budget needs a limit of at least 1, not {limit}"
            raise ValueError(msg)
        self._limit = limit
        self._running: dict[str, _Entry] = {}
        self._waiting: dict[str, _Entry] = {}  # insertion order is queue order

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def running(self) -> int:
        """Starts holding a slot."""
        return len(self._running)

    @property
    def waiting(self) -> int:
        """Starts queued behind the limit."""
        return len(self._waiting)

    def claim(
        self,
        execution_id: str,
        *,
        workflow_id: str,
        path: StartPath,
        resumed_from: str | None = None,
    ) -> StartClaim:
        """Take a place for ``execution_id``, holding a slot at once if one is free.

        Synchronous, so a caller can claim and create its task in one step.
        Raises :class:`StartAlreadyClaimedError` if this execution already
        holds a place: that is a duplicate start, and the second one must not
        run.
        """
        if execution_id in self._running or execution_id in self._waiting:
            raise StartAlreadyClaimedError(execution_id)
        claim = StartClaim(
            execution_id=execution_id,
            workflow_id=workflow_id,
            path=path,
            claimed_at=datetime.now(UTC),
            resumed_from=resumed_from,
        )
        self._waiting[execution_id] = _Entry(
            claim=claim, granted=asyncio.get_running_loop().create_future()
        )
        self._grant()
        position = self.position(execution_id)
        if position is not None and position.queued:
            logger.info(
                "Execution %s (%s) queued at position %d: %d of %d slots in use",
                execution_id,
                path.value,
                position.position,
                position.running,
                self._limit,
            )
        return claim

    @asynccontextmanager
    async def held(self, claim: StartClaim) -> AsyncIterator[None]:
        """Wait for ``claim``'s slot, hold it for the block, and give it back.

        Releases however the block ends, including cancellation while still
        queued, so an abandoned start never keeps its place.
        """
        try:
            entry = self._running.get(claim.execution_id) or self._waiting.get(claim.execution_id)
            if entry is None or entry.claim is not claim:
                msg = f"{claim.execution_id} holds no claim in this budget"
                raise RuntimeError(msg)
            await entry.granted
            yield
        finally:
            self.release(claim)

    def release(self, claim: StartClaim) -> None:
        """Give ``claim``'s place back. Idempotent; a stale claim releases nothing."""
        for table in (self._running, self._waiting):
            entry = table.get(claim.execution_id)
            if entry is not None and entry.claim is claim:
                del table[claim.execution_id]
                if not entry.granted.done():
                    entry.granted.cancel()
        self._grant()

    def position(self, execution_id: str) -> StartPosition | None:
        """Where ``execution_id`` stands, or None if it holds no place here."""
        running = self._running.get(execution_id)
        if running is not None:
            return self._at(running.claim, None)
        for index, (key, entry) in enumerate(self._waiting.items(), start=1):
            if key == execution_id:
                return self._at(entry.claim, index)
        return None

    def resume_of(self, parent_execution_id: str) -> StartPosition | None:
        """The place held by the child of ``parent_execution_id``'s resume, if any."""
        for entry in (*self._running.values(), *self._waiting.values()):
            if entry.claim.resumed_from == parent_execution_id:
                return self.position(entry.claim.execution_id)
        return None

    def matching(self, prefix: str) -> list[StartPosition]:
        """Every place whose execution id starts with ``prefix``, for id lookup."""
        ids = [key for key in (*self._running, *self._waiting) if key.startswith(prefix)]
        return [p for p in (self.position(i) for i in ids) if p is not None]

    def _at(self, claim: StartClaim, position: int | None) -> StartPosition:
        return StartPosition(
            claim=claim,
            position=position,
            running=len(self._running),
            waiting=len(self._waiting),
            limit=self._limit,
        )

    def _grant(self) -> None:
        """Hand free slots to the oldest waiters."""
        while len(self._running) < self._limit and self._waiting:
            execution_id = next(iter(self._waiting))
            entry = self._waiting.pop(execution_id)
            self._running[execution_id] = entry
            if not entry.granted.done():
                entry.granted.set_result(None)
