"""A start's reservation in the run queue, and what a refused one means (#1310 1.3).

Split from `WorkflowExecutionProcessor`: a start with a run queue is bracketed
as ``opening -> admitted`` (ADR-072 D2). The row is reserved BEFORE the stream
opens and promoted after it, so a crash between the two leaves an ``opening``
row the sweep settles by reading the stream, never a stream no row will run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_sourcing import StreamAlreadyExistsError

from syn_domain.contexts.orchestration._shared.event_epoch import ORCHESTRATION_EVENT_EPOCH

if TYPE_CHECKING:
    from syn_domain.contexts._shared.maintenance import AdmissionTicket
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
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


async def open_start(
    queue: ExecutionRunQueue | None,
    journal: ExecutionJournal,
    aggregate: WorkflowExecutionAggregate,
    admitted: AdmissionTicket | None,
    *,
    is_resume: bool,
) -> None:
    """Make the start durable; with a run queue, reserve before and promote after.

    Raises:
        StreamAlreadyExistsError: the execution already has a stream - it
            was started before, by this or another process.
    """
    execution_id = aggregate.id or ""
    if queue is not None:
        await reserve_run(queue, journal, execution_id, is_resume=is_resume)
    # #1387: durable, therefore visible. From the write the drain counts
    # this execution and a maintenance transition may proceed over it;
    # before it, it existed only as a queued task, and `set_mode(active=True)`
    # was waiting on this line. #1707: the write is also where whoever
    # queued it learns it started - not later, where an exception would
    # read as a start that never happened. If `open()` raised before the
    # write - a duplicate stream, a store that is down - the lease is
    # ended by the worker instead, which is the other honest answer:
    # nothing started.
    await journal.open(aggregate, written=admitted.mark_durable if admitted is not None else None)
    if queue is not None:
        await queue.mark_admitted(execution_id)
