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
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from event_sourcing import (
    DispatchContext,
    DomainEvent,
    EventEnvelope,
    ProjectionCheckpoint,
    ProjectionCheckpointStore,
    ProjectionResult,
)

from syn_domain.contexts._shared.integration_events import AdmissionOpenEvent
from syn_domain.contexts.orchestration._shared.start_todo import (
    ConditionalProjectionStore,
    StartFailureReporter,
    StartToDoProcessManager,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.legacy_event_shapes import (
    ResumedEventShape,
    classify_resumed_payload,
    payload_of,
    shape_of_resumed_payload,
)
from syn_domain.contexts.orchestration.slices.start_resume.value_objects import (
    ResumeStartRecord,
)

if TYPE_CHECKING:
    from syn_domain.contexts._shared.maintenance import AdmissionTicket

logger = logging.getLogger(__name__)


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


class ResumeStartProcessManager(StartToDoProcessManager[ResumeStartRecord]):
    """Starts the child execution of every admitted resume."""

    PROJECTION_NAME = "resume_start"
    VERSION = 1

    def __init__(
        self,
        resume_starter: ResumeStarter | None = None,
        store: ConditionalProjectionStore | None = None,
    ) -> None:
        super().__init__(store)
        self._starter = resume_starter

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
        """PROCESSOR SIDE: offer each owed start. Live-only, idempotent.

        The rules are the shared start to-do list's (`_shared/start_todo.py`).
        """
        return await super().process_pending()

    # -- the start to-do list's hooks -------------------------------------------

    def _record_type(self) -> type[ResumeStartRecord]:
        return ResumeStartRecord

    def _can_offer(self) -> bool:
        return self._starter is not None

    def _holds(self, record: ResumeStartRecord) -> bool:
        assert self._starter is not None
        return self._starter.holds_start(record.parent_execution_id)

    async def _offer(self, record: ResumeStartRecord, on_failure: StartFailureReporter) -> None:
        assert self._starter is not None
        await self._starter.start_resume(record.parent_execution_id, on_failure=on_failure)

    async def _settle_if_a_resume_started(self, event: DomainEvent) -> None:
        """Mark the parent's start done, once its CHILD says it started.

        A fact settles the to-do, not a dispatch. Pure and replay-safe.
        """
        origin = getattr(event, "resumed_from", None)
        parent = getattr(origin, "parent_execution_id", None)
        if parent:
            await self._settle_started(str(parent))

    def get_idempotency_key(self, todo_item: dict[str, str | int | float | bool | None]) -> str:
        """The parent's id: it admits at most one resume."""
        return str(todo_item.get("parent_execution_id", ""))
