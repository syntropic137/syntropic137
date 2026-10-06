"""Execution Request Start ProcessManager (#1557, ADR-025).

Subscribes to `ExecutionRequested` and starts the execution each admitted
direct start names, using the Processor To-Do List pattern shared with resume
starts (`_shared/start_todo.py`).

PROJECTION SIDE (handle_event): writes a `pending` record, and a terminal
`withdrawn` one when the request is withdrawn (#1650). Pure, replay-safe.
PROCESSOR SIDE (process_pending): offers each owed record to the starter. Live
only. A start the route already queued in this process is held, and is not
offered again; after a restart nothing is held, and every request still owed
is started from its record. Idempotent: the execution's stream opens with
NoStream, so a second start of one request is refused.
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
from syn_domain.contexts.orchestration._shared.start_record import read_start_record
from syn_domain.contexts.orchestration._shared.start_todo import (
    ConditionalProjectionStore,
    StartFailureReporter,
    StartToDoProcessManager,
)
from syn_domain.contexts.orchestration.slices.start_execution_request.value_objects import (
    ExecutionRequestStartRecord,
)

if TYPE_CHECKING:
    from syn_domain.contexts._shared.maintenance import AdmissionTicket

logger = logging.getLogger(__name__)

_EXECUTION_REQUESTED = "ExecutionRequested"
_EXECUTION_REQUEST_WITHDRAWN = "ExecutionRequestWithdrawn"
_EXECUTION_STARTED = "WorkflowExecutionStarted"
_ADMISSION_OPEN = AdmissionOpenEvent.event_type

_SUBSCRIBED_EVENTS = {
    _EXECUTION_REQUESTED,
    _EXECUTION_REQUEST_WITHDRAWN,
    _EXECUTION_STARTED,
    _ADMISSION_OPEN,
}


class ExecutionRequestStarter(Protocol):
    """Starts a requested execution behind the admission gate and the budget."""

    async def start_requested(
        self, execution_id: str, *, on_failure: StartFailureReporter
    ) -> AdmissionTicket | None:
        """Start it, or raise the synchronous refusal. Failures inside the start
        task are handed to ``on_failure``."""
        ...

    def holds_request(self, execution_id: str) -> bool:
        """Whether this execution's start is already queued or running HERE."""
        ...


class ExecutionRequestStartProcessManager(StartToDoProcessManager[ExecutionRequestStartRecord]):
    """Starts the execution of every admitted direct request."""

    PROJECTION_NAME = "execution_request_start"
    VERSION = 1

    def __init__(
        self,
        starter: ExecutionRequestStarter | None = None,
        store: ConditionalProjectionStore | None = None,
    ) -> None:
        super().__init__(store)
        self._starter = starter

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
        """PROJECTION SIDE: record the request as owed a start. No side effects.

        `AdmissionOpen` writes nothing; handling it makes the coordinator run
        the processor side, which re-offers starts held back by maintenance.
        """
        event_type = envelope.metadata.event_type or "Unknown"
        try:
            if event_type == _EXECUTION_REQUESTED:
                await self._record_request(envelope.event)
            elif event_type == _EXECUTION_REQUEST_WITHDRAWN:
                await self._record_withdrawal(envelope.event)
            elif event_type == _EXECUTION_STARTED:
                execution_id = getattr(envelope.event, "execution_id", None)
                if execution_id:
                    await self._settle_started(str(execution_id))
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
            logger.exception(
                "Error in execution request start process manager", extra={"type": event_type}
            )
            return ProjectionResult.FAILURE

    async def _record_request(self, event: DomainEvent) -> None:
        """Write a pending record, unless this request already has one.

        "Unless it has one" is part of the write, so a replay never resets a
        record another manager has since moved on.
        """
        if self._store is None:
            return
        execution_id = getattr(event, "execution_id", None)
        workflow_id = getattr(event, "workflow_id", None)
        requested_at = getattr(event, "requested_at", None)
        if not execution_id or not workflow_id:
            return
        record = ExecutionRequestStartRecord(
            execution_id=str(execution_id),
            workflow_id=str(workflow_id),
            recorded_at=requested_at if isinstance(requested_at, datetime) else datetime.now(UTC),
        )
        await self._store.save_if(self.PROJECTION_NAME, record.key, record, expected=None)

    async def _record_withdrawal(self, event: DomainEvent) -> None:
        """Settle the record `withdrawn`, so no pass offers it again (#1650).

        Over whatever it held short of `started`: a withdrawal landing on a
        `dispatched` record is the in-flight case, and the starter reads the
        request again once it has a slot, so that start does not run either.
        """
        if self._store is None:
            return
        execution_id = getattr(event, "execution_id", None)
        workflow_id = getattr(event, "workflow_id", None)
        withdrawn_at = getattr(event, "withdrawn_at", None)
        if not execution_id or not workflow_id:
            return
        row = await self._store.get(self.PROJECTION_NAME, str(execution_id))
        current = read_start_record(ExecutionRequestStartRecord, row) if row is not None else None
        if current is None:
            current = ExecutionRequestStartRecord(
                execution_id=str(execution_id),
                workflow_id=str(workflow_id),
                recorded_at=withdrawn_at
                if isinstance(withdrawn_at, datetime)
                else datetime.now(UTC),
            )
        reason = getattr(event, "reason", None)
        await self._save(
            current.model_copy(
                update={
                    "status": "withdrawn",
                    "status_reason": None if reason is None else str(reason),
                }
            )
        )

    async def process_pending(self) -> int:
        """PROCESSOR SIDE: offer each owed start. Live-only, idempotent.

        The rules are the shared start to-do list's (`_shared/start_todo.py`).
        """
        return await super().process_pending()

    # -- the start to-do list's hooks -------------------------------------------

    def _record_type(self) -> type[ExecutionRequestStartRecord]:
        return ExecutionRequestStartRecord

    def _can_offer(self) -> bool:
        return self._starter is not None

    def _holds(self, record: ExecutionRequestStartRecord) -> bool:
        assert self._starter is not None
        return self._starter.holds_request(record.execution_id)

    async def _offer(
        self, record: ExecutionRequestStartRecord, on_failure: StartFailureReporter
    ) -> None:
        assert self._starter is not None
        await self._starter.start_requested(record.execution_id, on_failure=on_failure)

    def get_idempotency_key(self, todo_item: dict[str, str | int | float | bool | None]) -> str:
        """The execution id: a request names exactly one execution."""
        return str(todo_item.get("execution_id", ""))
