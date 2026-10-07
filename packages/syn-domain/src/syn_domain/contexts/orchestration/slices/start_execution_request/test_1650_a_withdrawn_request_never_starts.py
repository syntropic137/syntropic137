"""#1650: a withdrawn request is settled on the start to-do list and stays settled.

The request ProcessManager's projection side, fed the events a request's own
stream holds. `test_1557_one_execution_budget.py` drives the same events
through the route, the dispatcher and the budget.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from event_sourcing.core.event import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.events.ExecutionRequestedEvent import (
    ExecutionRequestedEvent,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionRequestWithdrawnEvent import (
    ExecutionRequestWithdrawnEvent,
)
from syn_domain.contexts.orchestration.slices.start_execution_request import (
    ExecutionRequestStartProcessManager,
    ExecutionRequestStartRecord,
)

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_ID = "exec-1650withdrawn"


def _envelope(event: object, nonce: int) -> EventEnvelope:  # type: ignore[type-arg]
    return EventEnvelope(
        event=event,  # type: ignore[arg-type]
        metadata=EventMetadata(
            event_type=event.event_type,  # type: ignore[attr-defined]
            aggregate_id=f"request-{_ID}",
            aggregate_type="ExecutionRequest",
            aggregate_nonce=nonce,
            global_nonce=nonce,
        ),
    )


_REQUESTED = ExecutionRequestedEvent(
    execution_id=_ID, workflow_id="wf-1650", requested_at=datetime.now(UTC)
)
_WITHDRAWN = ExecutionRequestWithdrawnEvent(
    execution_id=_ID, workflow_id="wf-1650", reason="probe deadline", withdrawn_at=datetime.now(UTC)
)


class _Starter:
    def __init__(self) -> None:
        self.offered: list[str] = []

    async def start_requested(self, execution_id: str, *, on_failure: object) -> None:
        del on_failure
        self.offered.append(execution_id)

    def holds_request(self, execution_id: str) -> bool:
        del execution_id
        return False


async def _replayed(*events: object) -> tuple[ExecutionRequestStartProcessManager, _Starter]:
    starter = _Starter()
    manager = ExecutionRequestStartProcessManager(
        starter=starter,  # type: ignore[arg-type]
        store=InMemoryProjectionStore(),  # type: ignore[arg-type]
    )
    checkpoints = MemoryCheckpointStore()
    for nonce, event in enumerate(events, start=1):
        await manager.handle_event(_envelope(event, nonce), checkpoints)
    return manager, starter


async def _record(manager: ExecutionRequestStartProcessManager) -> ExecutionRequestStartRecord:
    row = await manager._store.get(manager.PROJECTION_NAME, _ID)  # pyright: ignore[reportPrivateUsage, reportOptionalMemberAccess]
    assert row is not None
    return ExecutionRequestStartRecord.model_validate(row)


async def test_a_withdrawn_request_is_settled_and_never_offered() -> None:
    manager, starter = await _replayed(_REQUESTED, _WITHDRAWN)

    record = await _record(manager)
    assert (record.status, record.status_reason) == ("withdrawn", "probe deadline")
    assert await manager.process_pending() == 0
    assert starter.offered == []


async def test_a_replayed_request_does_not_reopen_it() -> None:
    manager, starter = await _replayed(_REQUESTED, _WITHDRAWN, _REQUESTED)

    assert (await _record(manager)).status == "withdrawn"
    assert await manager.process_pending() == 0
    assert starter.offered == []


async def test_no_later_write_walks_it_back_to_owed() -> None:
    """Terminal in the record rules, not only by what reads it."""
    manager, _ = await _replayed(_REQUESTED, _WITHDRAWN)
    withdrawn = await _record(manager)

    written = await manager._save(withdrawn.model_copy(update={"status": "dispatched"}))  # pyright: ignore[reportPrivateUsage]

    assert written is False
    assert (await _record(manager)).status == "withdrawn"


async def test_an_execution_that_started_anyway_is_recorded_started() -> None:
    """The start's own event is the one fact that outranks a withdrawal."""
    manager, _ = await _replayed(_REQUESTED, _WITHDRAWN)

    await manager._settle_started(_ID)  # pyright: ignore[reportPrivateUsage]

    assert (await _record(manager)).status == "started"
