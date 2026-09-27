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
    OWED_STATUSES,
    ForkStartRecord,
    read_record,
)

if TYPE_CHECKING:
    from event_sourcing import ProjectionStore

logger = logging.getLogger(__name__)

_EXECUTION_FORKED = "ExecutionForked"

#: As on WorkflowDispatchProjection (#1387): subscribed for its side effect on
#: the coordinator, so a start held back by maintenance is re-offered once
#: admission reopens rather than when the next fork happens to arrive.
_ADMISSION_OPEN = AdmissionOpenEvent.event_type

_SUBSCRIBED_EVENTS = {_EXECUTION_FORKED, _ADMISSION_OPEN}


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
        for status in OWED_STATUSES:
            for row in await self._store.query(self.PROJECTION_NAME, filters={"status": status}):
                record = read_record(row)
                if record is not None:
                    records.append(record)
        return records

    async def _start(self, record: ForkStartRecord) -> bool:
        assert self._starter is not None
        parent = record.parent_execution_id
        try:
            await self._starter.start_fork(parent)
        except MaintenancePausedError as exc:
            logger.info("Start of the fork of %s held: %s", parent, exc.mode.refusal_detail)
            await self._save(record.model_copy(update={"status": "paused"}))
            return False
        except Exception as exc:
            # Terminal: a start the aggregate refused will be refused again.
            logger.exception("Could not start the fork of %s", parent)
            await self._save(
                record.model_copy(update={"status": "failed", "status_reason": str(exc)})
            )
            return False
        await self._save(record.model_copy(update={"status": "started", "status_reason": None}))
        return True

    async def _save(self, record: ForkStartRecord) -> None:
        assert self._store is not None
        await self._store.save(
            self.PROJECTION_NAME, record.parent_execution_id, record.model_dump(mode="json")
        )

    def get_idempotency_key(self, todo_item: dict[str, str | int | float | bool | None]) -> str:
        """The parent's id: it admits at most one fork."""
        return str(todo_item.get("parent_execution_id", ""))

    async def clear_all_data(self) -> None:
        if self._store is not None:
            await self._store.delete_all(self.PROJECTION_NAME)
