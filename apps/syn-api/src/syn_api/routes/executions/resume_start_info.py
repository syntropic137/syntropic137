"""A resumed parent's child start, as an operator sees it on the parent (#1480)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_api._wiring_admission import get_execution_budget
from syn_domain.contexts.orchestration import (
    MAX_START_ATTEMPTS,
    ResumeStartProcessManager,
    read_record,
)

from .models import ResumeStartInfo
from .queued_start import start_queue_info

if TYPE_CHECKING:
    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol


async def resume_start_of(
    store: ProjectionStoreProtocol, execution_id: str
) -> ResumeStartInfo | None:
    """The start of the child this execution's resume admitted, if it was resumed.

    Read straight from the `resume_start` to-do list, the record the process
    manager itself decides on, so what an operator sees is what will be retried.
    """
    row = await store.get(ResumeStartProcessManager.PROJECTION_NAME, execution_id)
    record = read_record(row) if row is not None else None
    if record is None:
        return None
    return ResumeStartInfo(
        status=record.status,
        status_reason=record.status_reason,
        attempts=record.attempts,
        max_attempts=MAX_START_ATTEMPTS,
        recorded_at=record.recorded_at,
        dispatched_at=record.dispatched_at,
        start_queue=start_queue_info(get_execution_budget().resume_of(execution_id)),
    )
