"""Resume Start ProcessManager (ADR-014 s7, ADR-025).

Subscribes to `ExecutionResumed` on a PARENT's stream and starts the child it
admitted, using the Processor To-Do List pattern.

PROJECTION SIDE (handle_event): writes a start record with status="pending".
  Called during both catch-up replay and live processing. Pure, replay-safe.

PROCESSOR SIDE (process_pending): starts each pending child.
  Called ONLY for live events, never during catch-up replay. Safe to repeat:
  a child that already started is recognised by its stream, not by this record,
  so a rebuilt to-do list cannot start any child twice.

Zero business logic: WHAT the child runs is decided by the parent aggregate
(`resume_start_command`) and refused by the child's (`refuse_resume_start`).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Protocol

from event_sourcing import (
    DispatchContext,
    DomainEvent,
    EventEnvelope,
    ProcessManager,
    ProjectionCheckpoint,
    ProjectionCheckpointStore,
    ProjectionResult,
    ProjectionStore,
)

from syn_domain.contexts._shared.integration_events import AdmissionOpenEvent
from syn_domain.contexts._shared.maintenance import AdmissionTicket, MaintenancePausedError
from syn_domain.contexts.orchestration.domain.aggregate_execution.legacy_event_shapes import (
    ResumedEventShape,
    classify_resumed_payload,
    payload_of,
    shape_of_resumed_payload,
)
from syn_domain.contexts.orchestration.slices.start_resume.value_objects import (
    DISPATCH_GRACE,
    MAX_START_ATTEMPTS,
    OWED_STATUSES,
    ResumeStartRecord,
    read_record,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = logging.getLogger(__name__)


def _may_replace(current: str, proposed: str) -> bool:
    """Whether a record in ``current`` may be overwritten with ``proposed``.

    `started` and `failed` are conclusions no later write may walk backwards.

    `started` replaces anything and nothing replaces it: the child's stream
    exists, which is a durable fact, and an existing child emits no second start
    event to restore a record that lost it. `failed` yields only to that fact.
    """
    if current == "started":
        return False
    if current == "failed":
        return proposed == "started"
    return True


def _is_a_resume(event: DomainEvent, aggregate_id: str | None) -> bool:
    """Whether a replayed `ExecutionResumed` is one, by payload shape.

    The event type alone used to decide this, which was the same fail-open the
    aggregate had: under ADR-023 a payload the typed validator refused replays
    as a generic event with its type intact, so a pre-rename un-pause would put
    a start on the to-do list for a child that was never admitted.

    Ambiguous raises, and the caller's handler reports it rather than recording
    a start it cannot justify.
    """
    payload = payload_of(event)
    shape = shape_of_resumed_payload(payload)
    if shape is ResumedEventShape.PRE_RENAME_UNPAUSE:
        logger.warning(
            "Ignoring a pre-rename ExecutionResumed (un-pause) on %s: it owes no start",
            aggregate_id,
            extra={"execution_id": aggregate_id},
        )
        return False
    if shape is ResumedEventShape.AMBIGUOUS:
        classify_resumed_payload(payload)  # raises, with the reason
    return True


_EXECUTION_RESUMED = "ExecutionResumed"

#: The pre-rename name for the SAME event. Subscribed because the rename moved
#: the `@event` registration, so a stored `ExecutionForked` resolves to no
#: concrete class and would reach no branch here. A resume that never gets a
#: to-do record is a child that never starts.
_EXECUTION_FORKED = "ExecutionForked"

#: How many times one write decides again after losing its compare-and-set.
#: Each loss means another writer's write landed, and a resume start has only a
#: handful of writers, so running out means the store refuses what it holds,
#: and that is reported rather than retried for ever.
_MAX_LOST_WRITES = 8

#: As on WorkflowDispatchProjection (#1387): subscribed for its side effect on
#: the coordinator, so a start held back by maintenance is re-offered once
#: admission reopens rather than when the next resume happens to arrive.
_ADMISSION_OPEN = AdmissionOpenEvent.event_type

#: The CHILD's own start. A resume start is only finished when the child stream
#: exists, and this event is the only thing that says so.
_EXECUTION_STARTED = "WorkflowExecutionStarted"

_SUBSCRIBED_EVENTS = {
    _EXECUTION_RESUMED,
    _EXECUTION_FORKED,
    _EXECUTION_STARTED,
    _ADMISSION_OPEN,
}


#: Told how a start that had already been handed to a task went wrong.
StartFailureReporter = Callable[[Exception], Awaitable[None]]


class ResumeStarter(Protocol):
    """Starts a resumed parent's child behind the admission gate (#1387).

    Returns the ticket the gate issued, so "started" is written from the
    admission decision and not from the absence of an exception - the same
    contract as `run_workflow` on the trigger path. Raises
    `MaintenancePausedError` synchronously when admission is closed.

    The start itself runs AFTER this returns, so a failure there cannot be
    raised to the caller. It is handed to ``on_failure`` instead, and a starter
    must do so: swallowing it into a log left the record `dispatched` and
    re-offered for ever, with no attempt counted and no reason (#1463).
    """

    async def start_resume(
        self, parent_execution_id: str, *, on_failure: StartFailureReporter
    ) -> AdmissionTicket | None: ...

    def holds_start(self, parent_execution_id: str) -> bool:
        """Whether a start for this parent's child is queued or running HERE.

        A `dispatched` record is re-offered after `DISPATCH_GRACE` because a
        process may have died with its start. But a start can also just be
        waiting for a slot in the execution budget for as long as the runs ahead
        of it take, and re-offering that one queued a duplicate task behind the
        first (#1557). The starter is the only thing that knows which case it
        is, so the processor asks before offering.
        """
        ...


class ConditionalProjectionStore(ProjectionStore, Protocol):
    """A projection store that can write a record only over the one it expects.

    Every write here is a read of the current record, a decision, then a save,
    and more than one process may be making them over the same row: two API
    processes, or a restarting coordinator beside one still draining. A lock in
    this class guards one instance only, so a stale write from another could
    still land between the read and the save and walk the record back -
    attempts and reason included (verification of #1466). The comparison and
    the write must be one operation in the store, which is the only thing every
    writer shares.
    """

    async def save_if(
        self, projection: str, key: str, record: BaseModel, *, expected: BaseModel | None
    ) -> bool:
        """Write ``record`` only while the store still holds ``expected``.

        The stored row is read as ``type(expected)`` and compared as a model,
        the way the caller compared it; None means "only while there is no row".
        True if written; False, with nothing written, if the row had moved on.
        """
        ...


def _write_is_allowed(
    *,
    key: str,
    unreadable: bool,
    current: ResumeStartRecord | None,
    writing: ResumeStartRecord,
    only_over: ResumeStartRecord | None,
) -> bool:
    """Whether `writing` may replace `current`, and why not when it may not.

    Extracted from `_save` so that method is the retry loop and this is the
    decision: three independent reasons to refuse a write is more branching than
    one function should carry, and the loop re-asks this question every time it
    loses a write.
    """
    if unreadable:
        # Logged by `read_record`. Nothing can be decided over a record that
        # cannot be read, and `process_pending` already skips it.
        return False
    if only_over is not None and current != only_over:
        logger.warning(
            "Not recording %s for the resume start of %s: its record moved on to %s",
            writing.status,
            key,
            None if current is None else current.status,
        )
        return False
    if current is not None and not _may_replace(current.status, writing.status):
        logger.debug(
            "Not walking the resume start of %s back from %s to %s",
            key,
            current.status,
            writing.status,
        )
        return False
    return True


class ResumeStartProcessManager(ProcessManager):
    """Starts the child execution of every admitted resume."""

    PROJECTION_NAME = "resume_start"
    VERSION = 1

    def __init__(
        self,
        resume_starter: ResumeStarter | None = None,
        store: ConditionalProjectionStore | None = None,
    ) -> None:
        self._starter = resume_starter
        self._store = store

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str] | None:
        return _SUBSCRIBED_EVENTS

    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: ProjectionCheckpointStore,
        context: DispatchContext | None = None,  # noqa: ARG002
    ) -> ProjectionResult:
        """PROJECTION SIDE: record the resume as owed a start. No side effects.

        `AdmissionOpen` writes nothing; handling it is what makes the
        coordinator run the processor side, which re-offers paused starts.
        """
        event_type = envelope.metadata.event_type or "Unknown"
        try:
            if event_type == _EXECUTION_RESUMED:
                if _is_a_resume(envelope.event, envelope.metadata.aggregate_id):
                    await self._record_resume(envelope.metadata.aggregate_id)
            elif event_type == _EXECUTION_FORKED:
                await self._record_resume(envelope.metadata.aggregate_id)
            elif event_type == _EXECUTION_STARTED:
                await self._settle_if_a_resume_started(envelope.event)
            await checkpoint_store.save_checkpoint(
                ProjectionCheckpoint(
                    projection_name=self.PROJECTION_NAME,
                    global_position=envelope.metadata.global_nonce or 0,
                    updated_at=datetime.now(UTC),
                    version=self.VERSION,
                )
            )
            return ProjectionResult.SUCCESS
        except Exception:
            logger.exception("Error in resume start process manager", extra={"type": event_type})
            return ProjectionResult.FAILURE

    async def _record_resume(self, parent_execution_id: str | None) -> None:
        """Write a pending record, unless this resume already has one.

        Never overwrites: a replay must not turn a started or failed record
        back into a pending one, nor a counted attempt back into none. "Unless
        it has one" is part of the write, not a read before it, so a second
        manager replaying the same resume cannot reset a record the first has
        since moved on.
        """
        if self._store is None or not parent_execution_id:
            return
        record = ResumeStartRecord(
            parent_execution_id=parent_execution_id, recorded_at=datetime.now(UTC)
        )
        await self._store.save_if(self.PROJECTION_NAME, parent_execution_id, record, expected=None)

    async def process_pending(self) -> int:
        """PROCESSOR SIDE: start each owed child. Live-only, idempotent."""
        if self._store is None or self._starter is None:
            return 0
        started = 0
        for record in await self._owed_records():
            if await self._start(record):
                started += 1
        return started

    async def _owed_records(self) -> list[ResumeStartRecord]:
        assert self._store is not None
        assert self._starter is not None
        records: list[ResumeStartRecord] = []
        now = datetime.now(UTC)
        for status in OWED_STATUSES:
            for row in await self._store.query(self.PROJECTION_NAME, filters={"status": status}):
                record = read_record(row)
                if record is None or not self._is_due(record, now):
                    continue
                # Owed on paper, already in hand here: its start is queued for a
                # slot or running. Offering it again is the #1557 duplicate.
                if self._starter.holds_start(record.parent_execution_id):
                    continue
                records.append(record)
        return records

    @staticmethod
    def _is_due(record: ResumeStartRecord, now: datetime) -> bool:
        """Whether an owed record should be offered again NOW.

        Only `dispatched` waits: its start is in flight, and the grace period is
        what keeps a slow child from being dispatched on every pass. Everything
        else owed - pending, paused, retryable - is due immediately, because
        nothing is running for it.
        """
        if record.status != "dispatched" or record.dispatched_at is None:
            return True
        return now - record.dispatched_at >= DISPATCH_GRACE

    async def _start(self, record: ResumeStartRecord) -> bool:
        assert self._starter is not None
        parent = record.parent_execution_id
        # BEFORE the dispatch, not after. `start_resume` spawns a task and returns,
        # so a child could open its stream and its start event settle this record
        # to `started` while a later `dispatched` save was still in flight -
        # overwriting the settle, after which nothing would ever settle it again
        # because an existing child emits no second start (codex review of
        # #1459).
        #
        # And only over the record this pass READ. Two passes can both read the
        # same owed record; the one that loses must not dispatch, and its stale
        # write must not revert whatever the winner's start has since recorded -
        # attempts and reason included, or the ceiling counts nothing (codex
        # review of #1466).
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
            await self._starter.start_resume(
                parent, on_failure=partial(self._record_failure, record, dispatched)
            )
        except Exception as exc:
            await self._record_failure(record, dispatched, exc)
            return False
        return True

    async def _record_failure(
        self, record: ResumeStartRecord, dispatched: ResumeStartRecord, exc: Exception
    ) -> None:
        """What a failed start means for its record, wherever it failed.

        One classification for both places a start can fail: synchronously, out
        of `start_resume`, and inside the task it spawned, reported back through
        `on_failure` (#1463). Two would drift, and the in-task one used to be a
        log line that counted nothing.

        ``record`` is the one this attempt was dispatched from, so ``attempts``
        counts from what was true before it. The failure is written only while
        the store still holds ``dispatched``, THIS attempt's dispatch, checked by
        `_save` in the same transition as the write. Either path can report
        late: the task runs the whole child, so its failure can arrive after the
        child's start settled the record, and while either path was failing a
        later pass may have dispatched again. A failure speaks for its own
        dispatch and never for whatever replaced it (codex review of #1466).
        """
        parent = record.parent_execution_id
        if isinstance(exc, MaintenancePausedError):
            logger.info("Start of the resume of %s held: %s", parent, exc.mode.refusal_detail)
            await self._save(record.model_copy(update={"status": "paused"}), only_over=dispatched)
            return
        if isinstance(exc, ValueError):
            # Terminal, and ONLY this. A `ValueError` here is the domain's own
            # refusal - `resume_rules.refuse_resume`, `refuse_resume_start`, the
            # aggregate's guards - and it is a function of recorded facts, so it
            # will be refused identically for ever. Retrying spends money to be
            # told the same thing.
            logger.warning("The resume of %s may not start: %s", parent, exc)
            await self._save(
                record.model_copy(update={"status": "failed", "status_reason": str(exc)}),
                only_over=dispatched,
            )
            return
        # NOT terminal. A store that is down, a repository read that timed out,
        # an artifact briefly unreachable - none of these say anything about
        # whether this resume MAY start, and marking them `failed` threw away an
        # admitted resume because of a blip (found by codex review).
        #
        # Deliberately typed rather than string-matched: the distinction is "did
        # the domain refuse", and that is what the exception TYPE says. Bounded,
        # so a permanent infrastructure fault still settles.
        attempts = record.attempts + 1
        exhausted = attempts >= MAX_START_ATTEMPTS
        logger.error(
            "Could not start the resume of %s (attempt %d of %d)",
            parent,
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

    async def _settle_if_a_resume_started(self, event: DomainEvent) -> None:
        """Mark the parent's start done, once its CHILD says it started.

        A fact settles the to-do, not a dispatch. Pure and replay-safe: it writes
        a projection row and nothing else, so replaying the stream re-derives the
        same statuses without starting anything.
        """
        if self._store is None:
            return
        origin = getattr(event, "resumed_from", None)
        parent = getattr(origin, "parent_execution_id", None)
        if not parent:
            return
        row = await self._store.get(self.PROJECTION_NAME, str(parent))
        record = read_record(row) if row is not None else None
        if record is None or record.status == "started":
            return
        await self._save(record.model_copy(update={"status": "started", "status_reason": None}))

    async def _save(
        self, record: ResumeStartRecord, *, only_over: ResumeStartRecord | None = None
    ) -> bool:
        """Write the record, never walking a settled one backwards. True if written.

        `started` and `failed` are conclusions; a later write of an earlier
        status is always a stale one racing them, so it is dropped (`_may_replace`).
        Monotonic rather than "last write wins", because last-write-wins is what
        let a dispatch overwrite the child's own start. With ``only_over``, the
        write happens only while the store still holds exactly that record: a
        compare-and-set, for every write made on behalf of one dispatch.

        The decision is made over what was read, and the write lands only while
        the store still holds exactly that (`save_if`), so no writer - in this
        process or another - can slip between them. A write that loses decides
        again over whatever beat it, because what beat it may be one it must
        not overwrite.
        """
        assert self._store is not None
        key = record.parent_execution_id
        for _ in range(_MAX_LOST_WRITES):
            row = await self._store.get(self.PROJECTION_NAME, key)
            current = read_record(row) if row is not None else None
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
            "Not recording %s for the resume start of %s: lost %d writes in a row",
            record.status,
            key,
            _MAX_LOST_WRITES,
        )
        return False

    def get_idempotency_key(self, todo_item: dict[str, str | int | float | bool | None]) -> str:
        """The parent's id: it admits at most one resume."""
        return str(todo_item.get("parent_execution_id", ""))

    async def clear_all_data(self) -> None:
        if self._store is not None:
            await self._store.delete_all(self.PROJECTION_NAME)
