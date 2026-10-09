"""A start's reservation in the run queue, and what a refused one means (#1310 1.3).

Split from `WorkflowExecutionProcessor`, which brackets the start as
``opening -> admitted`` (ADR-072 D2): the row is reserved BEFORE the stream
opens and promoted after it. This is the first half, and the only part of the
bracket that has a decision to make.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_sourcing import StreamAlreadyExistsError

from syn_domain.contexts.orchestration._shared.event_epoch import ORCHESTRATION_EVENT_EPOCH

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.ports import ExecutionRunQueue
    from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
        ExecutionJournal,
    )


async def reserve_run(
    queue: ExecutionRunQueue, journal: ExecutionJournal, execution_id: str, *, is_resume: bool
) -> None:
    """Reserve the execution's row, or decide what a refused ``reserve`` means.

    A refusal is decided from the stream, not the row. A row exists, but a row
    is a reservation, not a start: an ``opening`` or ``abandoned`` row whose
    stream write failed has no start at all, and calling it a duplicate would
    confirm a start that never happened. So only a stream that exists is a
    duplicate - promoted first, in case the earlier start died between its
    write and ``mark_admitted`` (D2). Absent, the start proceeds:
    ``journal.open``'s no-stream write is the fence, so a concurrent opener
    still loses there, honestly.

    Raises:
        StreamAlreadyExistsError: the execution's stream exists.
    """
    if await queue.reserve(execution_id, ORCHESTRATION_EVENT_EPOCH, is_resume=is_resume):
        return
    if await journal.reload(execution_id) is None:
        return
    await queue.mark_admitted(execution_id)
    raise StreamAlreadyExistsError(execution_id, 0)
