"""Workflow Dispatch ProcessManager.

Subscribes to TriggerFired events and dispatches workflow executions
via the ExecutionService, using the Processor To-Do List pattern (ADR-025).

PROJECTION SIDE (handle_event): writes dispatch records with status="pending".
  Called during both catch-up replay and live processing. Pure, replay-safe.

PROCESSOR SIDE (process_pending): reads pending records and dispatches.
  Called ONLY for live events, never during catch-up replay.
  The coordinator enforces this invariant.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from event_sourcing.core.checkpoint import DispatchContext

    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol

from event_sourcing import (
    DispatchContext,
    DomainEvent,
    EventEnvelope,
    ProcessManager,
    ProjectionCheckpoint,
    ProjectionCheckpointStore,
    ProjectionResult,
)

from syn_domain.contexts.github._shared.projection_names import WORKFLOW_DISPATCH


class _ExecutionService(Protocol):
    """Protocol for the execution service dependency."""

    async def run_workflow(
        self,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str,
        task: str | None = None,
    ) -> None: ...


class _BudgetChecker(Protocol):
    """Protocol for pre-dispatch budget validation."""

    async def check_budget(
        self,
        execution_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> object: ...

    async def allocate_budget(
        self,
        execution_id: str,
        workflow_type: str,
    ) -> object: ...


logger = logging.getLogger(__name__)

# Event types this projection subscribes to
_SUBSCRIBED_EVENTS = {
    "github.TriggerFired",
}


_Scalar = str | int | float | bool | None
_EventValue = _Scalar | dict[str, _Scalar]


def _to_str_dict(value: _EventValue) -> dict[str, str]:
    """Convert an arbitrary dict-like object to dict[str, str] by stringifying values."""
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items()}


class WorkflowDispatchProjection(ProcessManager):
    """Dispatches workflow executions when triggers fire.

    Implements the Processor To-Do List pattern (Dilger, Ch. 37):

    PROJECTION SIDE (handle_event):
      Writes dispatch records with status="pending" to the projection store.
      Called during both catch-up replay and live processing.
      MUST NOT call execution_service or produce any side effects.

    PROCESSOR SIDE (process_pending):
      Reads pending dispatch records and dispatches workflows.
      Called by the coordinator ONLY for live events.
      NOTE: dispatch is not yet fully idempotent - Phase A1 will add
      execution_id dedup at the handler level. Until then, the status
      field on dispatch records prevents re-processing of already-dispatched
      items within the same process lifecycle.
    """

    PROJECTION_NAME = WORKFLOW_DISPATCH
    VERSION = 1

    def __init__(
        self,
        execution_service: _ExecutionService | None = None,
        store: ProjectionStoreProtocol | None = None,
        budget_checker: _BudgetChecker | None = None,
        max_dispatches_per_hour: int = 50,
    ) -> None:
        self._execution_service = execution_service
        self._store = store
        self._budget_checker = budget_checker
        self._max_dispatches_per_hour = max_dispatches_per_hour
        self._dispatch_timestamps: list[float] = []

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
        """PROJECTION SIDE: Write dispatch records. No side effects.

        Writes a pending dispatch record for each TriggerFired event.
        The record is processed later by process_pending() (live-only).
        """
        event_type = envelope.metadata.event_type or "Unknown"
        event_data: dict[str, _EventValue] = envelope.event.model_dump()  # type: ignore[assignment]  # model_dump() -> dict[str, Any]
        global_nonce = envelope.metadata.global_nonce or 0

        try:
            if event_type == "github.TriggerFired":
                await self._write_dispatch_record(event_data)

            await checkpoint_store.save_checkpoint(
                ProjectionCheckpoint(
                    projection_name=self.PROJECTION_NAME,
                    global_position=global_nonce,
                    updated_at=datetime.now(UTC),
                    version=self.VERSION,
                )
            )
            return ProjectionResult.SUCCESS

        except Exception:
            logger.exception(
                "Error in dispatch projection",
                extra={"event_type": event_type},
            )
            return ProjectionResult.FAILURE

    def _check_dispatch_rate(self) -> bool:
        """Check if we're within the dispatch rate limit."""
        if self._max_dispatches_per_hour <= 0:
            return True
        now = time.monotonic()
        cutoff = now - 3600.0
        self._dispatch_timestamps = [t for t in self._dispatch_timestamps if t > cutoff]
        return len(self._dispatch_timestamps) < self._max_dispatches_per_hour

    async def process_pending(self) -> int:
        """PROCESSOR SIDE: Dispatch pending workflows. Live-only, idempotent.

        Called by the coordinator ONLY for live events, never during
        catch-up replay. The coordinator enforces this invariant.

        Returns:
            The number of items successfully dispatched.
        """
        if self._store is None or self._execution_service is None:
            return 0

        if not self._check_dispatch_rate():
            logger.warning(
                "Dispatch rate limit reached (%d/hour), skipping pending dispatches",
                self._max_dispatches_per_hour,
            )
            return 0

        pending = await self._store.query(self.PROJECTION_NAME, filters={"status": "pending"})
        processed = 0

        for record in pending:
            if await self._dispatch_record(record):
                processed += 1

        return processed

    async def _dispatch_record(self, record: dict[str, str | int | float | bool | None]) -> bool:
        """Dispatch a single pending record. Returns True if dispatched."""
        assert self._store is not None
        assert self._execution_service is not None

        execution_id = str(record.get("execution_id", ""))
        workflow_id = str(record.get("workflow_id", ""))
        trigger_id = record.get("trigger_id", "")

        if not workflow_id:
            logger.warning("Pending dispatch %s has no workflow_id, marking failed", trigger_id)
            await self._save_record_status(execution_id, record, "failed", "no_workflow_id")
            return False

        budget_ok = await self._check_budget(execution_id)
        if budget_ok is False:
            await self._save_record_status(execution_id, record, "failed", "budget_exceeded")
            return False

        try:
            await self._execute_and_record(record, execution_id, workflow_id, trigger_id)
            return True
        except Exception:
            logger.exception(
                "Failed to dispatch workflow %s for trigger %s", workflow_id, trigger_id
            )
            await self._save_record_status(execution_id, record, "failed", "dispatch_exception")
            return False

    async def _execute_and_record(
        self,
        record: dict[str, str | int | float | bool | None],
        execution_id: str,
        workflow_id: str,
        trigger_id: object,
    ) -> None:
        """Execute the workflow dispatch and record success."""
        assert self._store is not None
        assert self._execution_service is not None

        str_inputs = record.get("workflow_inputs", {})
        if not isinstance(str_inputs, dict):
            str_inputs = {}

        await self._execution_service.run_workflow(
            workflow_id=workflow_id,
            inputs=str_inputs,
            execution_id=execution_id,
        )

        record["status"] = "dispatched"
        record["dispatched_at"] = datetime.now(UTC).isoformat()
        if execution_id:
            await self._store.save(self.PROJECTION_NAME, execution_id, record)

        self._record_dispatch_timestamp()

        logger.info(
            "Dispatched workflow %s for trigger %s -> execution %s",
            workflow_id,
            trigger_id,
            execution_id,
        )

    def _record_dispatch_timestamp(self) -> None:
        """Track dispatch timestamp for rate limiting."""
        if self._max_dispatches_per_hour > 0:
            self._dispatch_timestamps.append(time.monotonic())

    async def _check_budget(self, execution_id: str) -> bool | None:
        """Check budget before dispatch. Returns False if blocked, None if no checker."""
        if self._budget_checker is None:
            return None
        try:
            result = await self._budget_checker.check_budget(
                execution_id=execution_id,
                input_tokens=0,
                output_tokens=0,
            )
            # Allocate only if no budget exists yet (idempotent on retry)
            if getattr(result, "budget", None) is None:
                await self._budget_checker.allocate_budget(
                    execution_id=execution_id,
                    workflow_type="custom",
                )
                result = await self._budget_checker.check_budget(
                    execution_id=execution_id,
                    input_tokens=0,
                    output_tokens=0,
                )
            if getattr(result, "allowed", True) is False:
                reason = str(getattr(result, "reason", "budget_exceeded"))
                logger.warning("Budget check failed for execution %s: %s", execution_id, reason)
                return False
        except Exception:
            logger.exception("Budget check error for execution %s", execution_id)
        return None

    async def _save_record_status(
        self,
        execution_id: str,
        record: dict[str, str | int | float | bool | None],
        status: str,
        reason: str,
    ) -> None:
        """Update a record's status and persist it."""
        assert self._store is not None
        record["status"] = status
        record["failure_reason"] = reason
        if execution_id:
            await self._store.save(self.PROJECTION_NAME, execution_id, record)

    def get_idempotency_key(self, todo_item: dict[str, str | int | float | bool | None]) -> str:
        """Dedup key is the execution_id - globally unique per dispatch."""
        return str(todo_item.get("execution_id", ""))

    async def clear_all_data(self) -> None:
        if self._store is not None:
            await self._store.delete_all(self.PROJECTION_NAME)

    async def _write_dispatch_record(self, event_data: dict[str, _EventValue]) -> None:
        """Write a pending dispatch record. No side effects."""
        workflow_id = str(event_data.get("workflow_id", ""))
        str_inputs = _to_str_dict(event_data.get("workflow_inputs", {}))
        execution_id = str(event_data.get("execution_id", ""))
        trigger_id = str(event_data.get("trigger_id", ""))

        dispatch_record: dict[str, str | dict[str, str] | None] = {
            "trigger_id": trigger_id,
            "execution_id": execution_id,
            "workflow_id": workflow_id,
            "workflow_inputs": str_inputs,
            "status": "pending",
            "dispatched_at": None,
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        if self._store is not None and execution_id:
            await self._store.save(self.PROJECTION_NAME, execution_id, dispatch_record)
