"""Fork Start ProcessManager (ADR-014 s7, ADR-025).

Subscribes to `ExecutionForked` on a PARENT's stream and starts the child it
admitted, using the Processor To-Do List pattern.

PROJECTION SIDE (handle_event): writes a start record with status="pending".
  Called during both catch-up replay and live processing. Pure, replay-safe.

PROCESSOR SIDE (process_pending): starts each pending child.
  Called ONLY for live events, never during catch-up replay. Safe to repeat:
  a child that already started is recognised by its stream, not by this record,
  so a rebuilt to-do list cannot start any child twice.

Zero business logic: WHAT the child runs is decided by the parent aggregate
(`fork_start_command`) and refused by the child's (`refuse_fork_start`).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from event_sourcing import (
    DispatchContext,
    DomainEvent,
    EventEnvelope,
    ProcessManager,
    ProjectionCheckpoint,
    ProjectionCheckpointStore,
    ProjectionResult,
)

from syn_domain.contexts._shared.integration_events import AdmissionOpenEvent
from syn_domain.contexts._shared.maintenance import AdmissionTicket, MaintenancePausedError
from syn_domain.contexts.orchestration.slices.start_fork.value_objects import (
    DISPATCH_GRACE,
    MAX_START_ATTEMPTS,
    OWED_STATUSES,
    ForkStartRecord,
    read_record,
)

if TYPE_CHECKING:
    from event_sourcing import ProjectionStore

logger = logging.getLogger(__name__)

#: Statuses no later write may walk backwards.
_SETTLED = frozenset({"started", "failed"})

_EXECUTION_FORKED = "ExecutionForked"

#: As on WorkflowDispatchProjection (#1387): subscribed for its side effect on
#: the coordinator, so a start held back by maintenance is re-offered once
#: admission reopens rather than when the next fork happens to arrive.
_ADMISSION_OPEN = AdmissionOpenEvent.event_type

#: The CHILD's own start. A fork start is only finished when the child stream
#: exists, and this event is the only thing that says so.
_EXECUTION_STARTED = "WorkflowExecutionStarted"

_SUBSCRIBED_EVENTS = {_EXECUTION_FORKED, _EXECUTION_STARTED, _ADMISSION_OPEN}


class ForkStarter(Protocol):
    """Starts a forked parent's child behind the admission gate (#1387).

    Returns the ticket the gate issued, so "started" is written from the
    admission decision and not from the absence of an exception - the same
    contract as `run_workflow` on the trigger path. Raises
    `MaintenancePausedError` synchronously when admission is closed.
    """

    async def start_fork(self, parent_execution_id: str) -> AdmissionTicket | None: ...


class ForkStartProcessManager(ProcessManager):
    """Starts the child execution of every admitted fork."""

    PROJECTION_NAME = "fork_start"
    VERSION = 1

    def __init__(
        self,
        fork_starter: ForkStarter | None = None,
        store: ProjectionStore | None = None,
    ) -> None:
        self._starter = fork_starter
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
        """PROJECTION SIDE: record the fork as owed a start. No side effects.

        `AdmissionOpen` writes nothing; handling it is what makes the
        coordinator run the processor side, which re-offers paused starts.
        """
        event_type = envelope.metadata.event_type or "Unknown"
        try:
            if event_type == _EXECUTION_FORKED:
                await self._record_fork(envelope.metadata.aggregate_id)
            elif event_type == _EXECUTION_STARTED:
                await self._settle_if_a_fork_started(envelope.event)
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
            logger.exception("Error in fork start process manager", extra={"type": event_type})
            return ProjectionResult.FAILURE

    async def _record_fork(self, parent_execution_id: str | None) -> None:
        """Write a pending record, unless this fork already has one.

        Never overwrites: a replay must not turn a started or failed record
        back into a pending one.
        """
        if self._store is None or not parent_execution_id:
            return
        if await self._store.get(self.PROJECTION_NAME, parent_execution_id) is not None:
            return
        record = ForkStartRecord(
            parent_execution_id=parent_execution_id, recorded_at=datetime.now(UTC)
        )
        await self._save(record)

    async def process_pending(self) -> int:
        """PROCESSOR SIDE: start each owed child. Live-only, idempotent."""
        if self._store is None or self._starter is None:
            return 0
        started = 0
        for record in await self._owed_records():
            if await self._start(record):
                started += 1
        return started

    async def _owed_records(self) -> list[ForkStartRecord]:
        assert self._store is not None
        records: list[ForkStartRecord] = []
        now = datetime.now(UTC)
        for status in OWED_STATUSES:
            for row in await self._store.query(self.PROJECTION_NAME, filters={"status": status}):
                record = read_record(row)
                if record is None or not self._is_due(record, now):
                    continue
                records.append(record)
        return records

    @staticmethod
    def _is_due(record: ForkStartRecord, now: datetime) -> bool:
        """Whether an owed record should be offered again NOW.

        Only `dispatched` waits: its start is in flight, and the grace period is
        what keeps a slow child from being dispatched on every pass. Everything
        else owed - pending, paused, retryable - is due immediately, because
        nothing is running for it.
        """
        if record.status != "dispatched" or record.dispatched_at is None:
            return True
        return now - record.dispatched_at >= DISPATCH_GRACE

    async def _start(self, record: ForkStartRecord) -> bool:
        assert self._starter is not None
        parent = record.parent_execution_id
        # BEFORE the dispatch, not after. `start_fork` spawns a task and returns,
        # so a child could open its stream and its start event settle this record
        # to `started` while a later `dispatched` save was still in flight -
        # overwriting the settle, after which nothing would ever settle it again
        # because an existing child emits no second start (codex review of
        # #1459).
        await self._save(
            record.model_copy(
                update={
                    "status": "dispatched",
                    "status_reason": None,
                    "dispatched_at": datetime.now(UTC),
                }
            )
        )
        try:
            await self._starter.start_fork(parent)
        except MaintenancePausedError as exc:
            logger.info("Start of the fork of %s held: %s", parent, exc.mode.refusal_detail)
            await self._save(record.model_copy(update={"status": "paused"}))
            return False
        except ValueError as exc:
            # Terminal, and ONLY this. A `ValueError` here is the domain's own
            # refusal - `fork_rules.refuse_fork`, `refuse_fork_start`, the
            # aggregate's guards - and it is a function of recorded facts, so it
            # will be refused identically for ever. Retrying spends money to be
            # told the same thing.
            logger.warning("The fork of %s may not start: %s", parent, exc)
            await self._save(
                record.model_copy(update={"status": "failed", "status_reason": str(exc)})
            )
            return False
        except Exception as exc:
            # NOT terminal. A store that is down, a repository read that timed
            # out, an artifact briefly unreachable - none of these say anything
            # about whether this fork MAY start, and marking them `failed` threw
            # away an admitted fork because of a blip (found by codex review).
            #
            # Deliberately typed rather than string-matched: the distinction is
            # "did the domain refuse", and that is what the exception TYPE says.
            # Bounded, so a permanent infrastructure fault still settles.
            attempts = record.attempts + 1
            exhausted = attempts >= MAX_START_ATTEMPTS
            logger.exception(
                "Could not start the fork of %s (attempt %d of %d)",
                parent,
                attempts,
                MAX_START_ATTEMPTS,
            )
            await self._save(
                record.model_copy(
                    update={
                        "status": "failed" if exhausted else "retryable",
                        "status_reason": str(exc),
                        "attempts": attempts,
                    }
                )
            )
            return False
        return True

    async def _settle_if_a_fork_started(self, event: DomainEvent) -> None:
        """Mark the parent's start done, once its CHILD says it started.

        A fact settles the to-do, not a dispatch. Pure and replay-safe: it writes
        a projection row and nothing else, so replaying the stream re-derives the
        same statuses without starting anything.
        """
        if self._store is None:
            return
        origin = getattr(event, "forked_from", None)
        parent = getattr(origin, "parent_execution_id", None)
        if not parent:
            return
        row = await self._store.get(self.PROJECTION_NAME, str(parent))
        record = read_record(row) if row is not None else None
        if record is None or record.status == "started":
            return
        await self._save(record.model_copy(update={"status": "started", "status_reason": None}))

    async def _save(self, record: ForkStartRecord) -> None:
        """Write the record, never walking a settled one backwards.

        `started` and `failed` are conclusions; a later write of an earlier
        status is always a stale one racing them, so it is dropped. Monotonic
        rather than "last write wins", because last-write-wins is what let a
        dispatch overwrite the child's own start.
        """
        assert self._store is not None
        if record.status not in _SETTLED:
            current = read_record(
                await self._store.get(self.PROJECTION_NAME, record.parent_execution_id)
            )
            if current is not None and current.status in _SETTLED:
                logger.debug(
                    "Not walking the fork start of %s back from %s to %s",
                    record.parent_execution_id,
                    current.status,
                    record.status,
                )
                return
        await self._store.save(
            self.PROJECTION_NAME, record.parent_execution_id, record.model_dump(mode="json")
        )

    def get_idempotency_key(self, todo_item: dict[str, str | int | float | bool | None]) -> str:
        """The parent's id: it admits at most one fork."""
        return str(todo_item.get("parent_execution_id", ""))

    async def clear_all_data(self) -> None:
        if self._store is not None:
            await self._store.delete_all(self.PROJECTION_NAME)
