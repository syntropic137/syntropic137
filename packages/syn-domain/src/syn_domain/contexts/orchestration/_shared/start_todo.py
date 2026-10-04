"""The start to-do list every execution start path shares (ADR-014 s7, #1557).

Two ProcessManagers start executions from durable intents: the start of a
resumed parent's child (`ResumeStartProcessManager`) and the start of a direct
request (`ExecutionRequestStartProcessManager`). They differ in what admits the
start and what the starter is asked to do; everything about the RECORD - its
statuses, when it is offered again, how a failure is classified and how a write
is fenced against a concurrent one - is the same, and lives here once.

PROJECTION SIDE (subclass `handle_event`): writes `pending` records. Pure.
PROCESSOR SIDE (`process_pending`): offers each owed record. Live-only, and
idempotent because the execution a record names has a fixed id and its stream
refuses a second start.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Protocol

from event_sourcing import ProcessManager, ProjectionStore

from syn_domain.contexts._shared.maintenance import MaintenancePausedError
from syn_domain.contexts.orchestration._shared.start_record import (
    StartRecord,
    StartStatus,
    read_start_record,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = logging.getLogger(__name__)

#: Statuses still owed a start.
#:
#: `paused` is reversible, never terminal. `retryable` is a start that failed for
#: a reason that may not recur. `dispatched` is the subtle one: the start was
#: handed to a background task and NOTHING yet proves an execution exists. It
#: stays owed until the execution's own `WorkflowExecutionStarted` says
#: otherwise; re-offering is safe because the execution's id is fixed by the
#: intent and its stream refuses a second start (codex review of #1459).
OWED_STATUSES: tuple[StartStatus, ...] = ("pending", "paused", "retryable", "dispatched")

#: How long a `dispatched` start is left alone before it is re-offered.
#:
#: Re-offering inside the window is not harmful - the id is fixed and the start
#: is refused - but it is not free either: each re-offer takes an admission
#: ticket (codex review of #1459). So it waits. A start still queued for an
#: execution-budget slot is never re-offered at all: the starter reports it
#: held (#1557).
DISPATCH_GRACE = timedelta(minutes=5)

#: How many times a start may be attempted before `retryable` becomes `failed`.
#:
#: A CEILING, not a tuning knob. Without one, a start that fails the same way
#: for ever is retried for ever, and each attempt can provision a workspace.
MAX_START_ATTEMPTS = 3

#: How many times one write decides again after losing its compare-and-set.
_MAX_LOST_WRITES = 8

#: Told how a start that had already been handed to a task went wrong.
StartFailureReporter = Callable[[Exception], Awaitable[None]]


class ConditionalProjectionStore(ProjectionStore, Protocol):
    """A projection store that can write a record only over the one it expects.

    Every write here is a read, a decision, then a save, and more than one
    process may be making them over the same row. The comparison and the write
    must be one operation in the store, which is the only thing every writer
    shares (verification of #1466).
    """

    async def save_if(
        self, projection: str, key: str, record: BaseModel, *, expected: BaseModel | None
    ) -> bool:
        """Write ``record`` only while the store still holds ``expected``.

        True if written; False, with nothing written, if the row had moved on.
        """
        ...


def _may_replace(current: str, proposed: str) -> bool:
    """`started` and `failed` are conclusions no later write may walk backwards.

    `started` replaces anything and nothing replaces it: the execution's stream
    exists. `failed` yields only to that fact.
    """
    if current == "started":
        return False
    if current == "failed":
        return proposed == "started"
    return True


def _write_is_allowed(
    *,
    key: str,
    unreadable: bool,
    current: StartRecord | None,
    writing: StartRecord,
    only_over: StartRecord | None,
) -> bool:
    """Whether `writing` may replace `current`, and why not when it may not."""
    if unreadable:
        return False
    if only_over is not None and current != only_over:
        logger.warning(
            "Not recording %s for the start of %s: its record moved on to %s",
            writing.status,
            key,
            None if current is None else current.status,
        )
        return False
    if current is not None and not _may_replace(current.status, writing.status):
        logger.debug(
            "Not walking the start of %s back from %s to %s", key, current.status, writing.status
        )
        return False
    return True


class StartToDoProcessManager[R: StartRecord](ProcessManager):
    """The processor side and the record rules of a start to-do list."""

    PROJECTION_NAME: str

    def __init__(self, store: ConditionalProjectionStore | None) -> None:
        self._store = store

    # -- what a subclass decides -----------------------------------------------

    @abstractmethod
    def _record_type(self) -> type[R]:
        """The record model rows of this list are read as."""

    @abstractmethod
    def _can_offer(self) -> bool:
        """Whether this manager was given a starter at all."""

    @abstractmethod
    async def _offer(self, record: R, on_failure: StartFailureReporter) -> None:
        """Hand the start to the starter. Raises a synchronous refusal."""

    @abstractmethod
    def _holds(self, record: R) -> bool:
        """Whether the starter already has this start queued or running (#1557)."""

    # -- the processor side ------------------------------------------------------

    async def process_pending(self) -> int:
        """PROCESSOR SIDE: offer each owed start. Live-only, idempotent."""
        if self._store is None or not self._can_offer():
            return 0
        started = 0
        for record in await self._owed_records():
            if await self._start(record):
                started += 1
        return started

    async def _owed_records(self) -> list[R]:
        assert self._store is not None
        records: list[R] = []
        now = datetime.now(UTC)
        for status in OWED_STATUSES:
            for row in await self._store.query(self.PROJECTION_NAME, filters={"status": status}):
                record = read_start_record(self._record_type(), row)
                if record is None or not self._is_due(record, now):
                    continue
                # Owed on paper, already in hand here: its start is queued for a
                # slot or running. Offering it again is the #1557 duplicate.
                if self._holds(record):
                    continue
                records.append(record)
        return records

    @staticmethod
    def _is_due(record: StartRecord, now: datetime) -> bool:
        """Only `dispatched` waits: its start is in flight. Everything else owed
        - pending, paused, retryable - is due now, because nothing runs for it."""
        if record.status != "dispatched" or record.dispatched_at is None:
            return True
        return now - record.dispatched_at >= DISPATCH_GRACE

    async def _start(self, record: R) -> bool:
        # `dispatched` BEFORE the offer, and only over the record this pass READ:
        # the offer spawns a task whose start may settle the record before a
        # later write lands, and a pass that lost the race must neither offer
        # nor revert the winner's record (codex reviews of #1459, #1466).
        dispatched = record.model_copy(
            update={
                "status": "dispatched",
                "status_reason": None,
                "dispatched_at": datetime.now(UTC),
            }
        )
        if not await self._save(dispatched, only_over=record):
            return False
        try:
            await self._offer(record, partial(self._record_failure, record, dispatched))
        except Exception as exc:
            await self._record_failure(record, dispatched, exc)
            return False
        return True

    async def _record_failure(self, record: R, dispatched: R, exc: Exception) -> None:
        """What a failed start means for its record, wherever it failed.

        One classification for a synchronous refusal and a failure inside the
        spawned task (#1463). Written only while the store still holds THIS
        attempt's dispatch: a failure speaks for its own dispatch and never for
        whatever replaced it (codex review of #1466).
        """
        key = record.key
        if isinstance(exc, MaintenancePausedError):
            logger.info("Start of %s held: %s", key, exc.mode.refusal_detail)
            await self._save(record.model_copy(update={"status": "paused"}), only_over=dispatched)
            return
        if isinstance(exc, ValueError):
            # Terminal, and ONLY this: the domain's own refusal is a function of
            # recorded facts and will be refused identically for ever.
            logger.warning("The start of %s may not happen: %s", key, exc)
            await self._save(
                record.model_copy(update={"status": "failed", "status_reason": str(exc)}),
                only_over=dispatched,
            )
            return
        # NOT terminal: a store that is down says nothing about whether this
        # start MAY happen. Bounded, so a permanent fault still settles.
        attempts = record.attempts + 1
        exhausted = attempts >= MAX_START_ATTEMPTS
        logger.error(
            "Could not start %s (attempt %d of %d)",
            key,
            attempts,
            MAX_START_ATTEMPTS,
            exc_info=exc,
        )
        await self._save(
            record.model_copy(
                update={
                    "status": "failed" if exhausted else "retryable",
                    "status_reason": str(exc),
                    "attempts": attempts,
                }
            ),
            only_over=dispatched,
        )

    async def _settle_started(self, key: str) -> None:
        """Mark a start done because its execution says it started. Pure."""
        if self._store is None:
            return
        row = await self._store.get(self.PROJECTION_NAME, key)
        record = read_start_record(self._record_type(), row) if row is not None else None
        if record is None or record.status == "started":
            return
        await self._save(record.model_copy(update={"status": "started", "status_reason": None}))

    async def _save(self, record: R, *, only_over: R | None = None) -> bool:
        """Write the record, never walking a settled one backwards. True if written.

        Monotonic rather than last-write-wins, and compare-and-set in the store
        (`save_if`), so no writer - in this process or another - can slip
        between the decision and the write. A write that loses decides again
        over whatever beat it.
        """
        assert self._store is not None
        key = record.key
        for _ in range(_MAX_LOST_WRITES):
            row = await self._store.get(self.PROJECTION_NAME, key)
            current = read_start_record(self._record_type(), row) if row is not None else None
            if not _write_is_allowed(
                key=key,
                unreadable=row is not None and current is None,
                current=current,
                writing=record,
                only_over=only_over,
            ):
                return False
            if await self._store.save_if(self.PROJECTION_NAME, key, record, expected=current):
                return True
        logger.error(
            "Not recording %s for the start of %s: lost %d writes in a row",
            record.status,
            key,
            _MAX_LOST_WRITES,
        )
        return False

    async def clear_all_data(self) -> None:
        if self._store is not None:
            await self._store.delete_all(self.PROJECTION_NAME)
