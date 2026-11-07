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
from syn_domain.contexts.orchestration._shared.resume_withdrawal import ResumeWithdrawnError
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    CancelExecutionCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    EventsNotRecordedError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.run_todo_fold import (
    RunScopedTodoFold,
)
from syn_shared.control import ControlSignalType

if TYPE_CHECKING:
    from syn_domain.contexts._shared.maintenance import AdmissionTicket
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.ports import ExecutionRunQueue
    from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
        ExecutionJournal,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        ExecutionRepository,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.run_todo_fold import (
        ExecutionEventStream,
        TodoProjectionType,
    )

_CANCEL_ATTEMPTS = 3
"""Reads of the child a withdrawal's cancel may take. Two writers race at most
(the opener and one claimer), so the second read already sees the winner."""


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
    # #1677: before the promotion, so no executor can claim the row of a child
    # whose resume was withdrawn while it opened. The row is still promoted,
    # so the claimer closes it from the cancelled stream like any cancelled run.
    withdrawn = await cancel_if_withdrawn(journal, aggregate)
    if queue is not None:
        await queue.mark_admitted(execution_id)
    if withdrawn is not None:
        raise ResumeWithdrawnError(execution_id)


async def cancel_if_withdrawn(
    journal: ExecutionJournal, aggregate: WorkflowExecutionAggregate
) -> WorkflowExecutionAggregate | None:
    """Cancel a resumed child whose parent's resume was withdrawn (#1677).

    The start reads the parent once it holds a slot, but awaits again before
    its stream opens, and a cancel landing there finds no child and answers
    "it will not run". So the parent is read again AFTER the open, as the
    cancel reads the child after recording the withdrawal: whichever of the
    two writes lands second sees the other, and the child never runs. The
    opener asks before it promotes the row, and the claimer asks again before
    it drains, because the ``opening`` sweep may promote a row on its own.

    Returns:
        The child as it now stands, cancelled, or None if it was not withdrawn.

    Raises:
        EventsNotRecordedError: see `_cancel_withdrawn_child`.
    """
    origin = aggregate.start_pins.resumed_from
    if origin is None:
        return None
    parent = await journal.reload(origin.parent_execution_id)
    if parent is None or not parent.resume_withdrawn:
        return None
    return await _cancel_withdrawn_child(journal, aggregate.id or "", origin.resume_phase_id)


async def _cancel_withdrawn_child(
    journal: ExecutionJournal, child_id: str, resume_phase_id: str
) -> WorkflowExecutionAggregate:
    """Cancel the child, or find it already cancelled by the other side.

    The opener and a claimer may both find the child cancellable and both
    append the cancel. The one that loses the version race reads the child
    again and finds the cancel the other wrote, which is the answer it wanted:
    a lost race is not an error here, and an error escaping the claimer's
    drain would keep its claim charged until the lease expires.

    Raises:
        EventsNotRecordedError: the cancel was not shown recorded, by this
            writer or another, after `_CANCEL_ATTEMPTS` reads of the child.
        LookupError: the child has no stream.
    """
    attempt = 0
    while True:
        attempt += 1
        child = await journal.reload(child_id)
        if child is None:
            msg = f"Withdrawn resume child {child_id} has no execution stream"
            raise LookupError(msg)
        if not child.accepts_control(ControlSignalType.CANCEL):
            return child
        child.cancel_execution(
            CancelExecutionCommand(
                execution_id=child_id,
                phase_id=resume_phase_id,
                reason="Withdrawn before it started",
            )
        )
        try:
            await journal.append(child)
        except EventsNotRecordedError:
            # Lost the race, or the acknowledgment: the next read decides.
            if attempt >= _CANCEL_ATTEMPTS:
                raise
            continue
        return child


async def fold_claimed_run(
    execution_id: str,
    repository: ExecutionRepository,
    events: ExecutionEventStream,
    projection_type: TodoProjectionType,
) -> tuple[RunScopedTodoFold, WorkflowExecutionAggregate]:
    """The claimed run's own to-do fold and aggregate, a withdrawn resume cancelled.

    A withdrawn resume drains as the cancelled run it now is (#1677). The
    opener may write that cancel after this fold was seeded, so it is folded
    again: a stale fold still holds the first phase's to-do, and draining it
    would start a phase on a cancelled run.

    Raises:
        LookupError: the claimed execution has no stream.
    """
    fold = await RunScopedTodoFold.for_execution(execution_id, repository, events, projection_type)
    aggregate = await fold.journal.reload(execution_id)
    if aggregate is None:
        msg = f"Claimed run {execution_id} has no execution stream"
        raise LookupError(msg)
    if await cancel_if_withdrawn(fold.journal, aggregate) is None:
        return fold, aggregate
    fold = await RunScopedTodoFold.for_execution(execution_id, repository, events, projection_type)
    return fold, await fold.journal.reload(execution_id) or aggregate
