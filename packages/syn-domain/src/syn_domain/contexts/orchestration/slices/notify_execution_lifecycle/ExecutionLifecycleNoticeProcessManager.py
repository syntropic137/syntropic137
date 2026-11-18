"""Execution Lifecycle Notice ProcessManager (#1661, ADR-025).

Subscribes to the terminal events and tells an `ExecutionLifecycleSinkPort`
how each execution ended, using the Processor To-Do List pattern.

PROJECTION SIDE (handle_event): writes one owed record per (execution_id,
  outcome) from `lifecycle_notice`. Pure, replay-safe: a replayed event whose
  record already exists, owed or delivered, writes nothing, so a delivered
  notice is never reopened. A row that cannot be read is replaced as owed.

PROCESSOR SIDE (process_pending): delivers each owed record through the sink
  and marks it delivered. Called ONLY for live events, never during catch-up
  replay. A delivery the sink raised on stays owed for the next pass; the
  platform's clock tick guarantees a pass comes on a quiet system too.

Zero business logic: what a notice says is decided by `lifecycle_notice`, and
where it goes by the sink.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar

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

from syn_domain.contexts.orchestration.slices.notify_execution_lifecycle.value_objects import (
    LifecycleNoticeRecord,
    NoticeDelivery,
    lifecycle_notice,
    read_record,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.ports.ExecutionLifecycleSinkPort import (
        ExecutionLifecycleSinkPort,
    )

logger = logging.getLogger(__name__)

#: The events `lifecycle_notice` derives a notice from.
_TERMINAL_EVENTS = {"WorkflowCompleted", "WorkflowFailed", "ExecutionCancelled"}
#: The platform's durable clock: one `InventoryReconciliationSweep` per interval.
#: Subscribed so a delivery the sink refused is retried with no later event to
#: carry it. Named by string: a tick carries no data this reads.
_CLOCK_TICK = "InventoryReconciliationSweep"


class ExecutionLifecycleNoticeProcessManager(ProcessManager):
    """Tells a sink, once, how each execution ended."""

    PROJECTION_NAME = "execution_lifecycle_notice"
    VERSION = 1
    SIDE_EFFECTS_ALLOWED: ClassVar[bool] = True

    def __init__(self, sink: ExecutionLifecycleSinkPort, store: ProjectionStore) -> None:
        self._sink = sink
        self._store = store

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str] | None:
        return {*_TERMINAL_EVENTS, _CLOCK_TICK}

    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: ProjectionCheckpointStore,
        context: DispatchContext | None = None,  # noqa: ARG002
    ) -> ProjectionResult:
        """PROJECTION SIDE: record each terminal event's notice as owed. No side effects."""
        event_type = envelope.metadata.event_type or "Unknown"
        try:
            notice = lifecycle_notice(envelope.event)
            if notice is not None:
                record = LifecycleNoticeRecord(notice=notice)
                # Readable, owed or delivered: a replay, so write nothing. An
                # unreadable row is no record at all, so it is owed afresh.
                row = await self._store.get(self.PROJECTION_NAME, record.key)
                if row is None or read_record(row) is None:
                    await self._save(record)
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
                "Error in execution lifecycle notice process manager", extra={"type": event_type}
            )
            return ProjectionResult.FAILURE

    async def process_pending(self) -> int:
        """PROCESSOR SIDE: deliver each owed notice. Live-only; returns how many went."""
        delivered = 0
        rows = await self._store.query(
            self.PROJECTION_NAME, filters={"delivery": NoticeDelivery.OWED.value}
        )
        for row in rows:
            record = read_record(row)
            if record is None:
                continue
            try:
                await self._sink.deliver(record.notice)
            except Exception:
                # Left owed: the next live pass, at worst the next clock tick,
                # offers it again. The sink is idempotent per key, so a
                # delivery that landed before this raised is not doubled.
                logger.exception("Could not deliver the execution lifecycle notice %s", record.key)
                continue
            await self._save(record.model_copy(update={"delivery": NoticeDelivery.DELIVERED}))
            delivered += 1
        return delivered

    async def _save(self, record: LifecycleNoticeRecord) -> None:
        await self._store.save(self.PROJECTION_NAME, record.key, record.model_dump(mode="json"))

    def get_idempotency_key(self, todo_item: dict[str, str | int | float | bool | None]) -> str:
        """One notice per (execution_id, outcome): the `key` every stored row carries."""
        return str(todo_item["key"])

    async def clear_all_data(self) -> None:
        await self._store.delete_all(self.PROJECTION_NAME)
