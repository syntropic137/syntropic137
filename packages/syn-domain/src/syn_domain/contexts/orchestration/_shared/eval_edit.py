"""The one load-decide-save path behind UpdateEval, FreezeEval and ArchiveEval (#967).

Mirrors ``tag_edit.edit_tags``. The three slices differ only in which aggregate
method they call, so they share this to agree on the rest: an unknown eval is
``None``, a broken rule is a failed ``HandlerResult`` with nothing written, and
a command that changes nothing succeeds and writes nothing.

A stale write is NOT caught here. The repository saves at the version the
aggregate was loaded at, so an Update racing a Freeze loses with
``ConcurrencyConflictError``; that reaches the caller, which maps it to a
conflict the same way it does for every other aggregate.

The one exception is a one-way switch. Two FreezeEval (or two ArchiveEval)
decided from the same version both want the same end state, and the loser
finds it already recorded. Such a caller passes ``settled``: on a conflict the
eval is reloaded, and if ``settled`` holds the duplicate succeeds having
written nothing. Anything else, including a rival that changed something
different, is still a conflict.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_sourcing import ConcurrencyConflictError

from syn_domain.contexts.orchestration.domain import HandlerResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from syn_domain.contexts.orchestration._shared.tag_edit import EventPublisher
    from syn_domain.contexts.orchestration.domain.aggregate_eval.EvalAggregate import (
        EvalAggregate,
    )
    from syn_domain.repository import Repository


async def edit_eval(
    repository: Repository[EvalAggregate],
    eval_id: str,
    decide: Callable[[EvalAggregate], None],
    event_publisher: EventPublisher | None = None,
    settled: Callable[[EvalAggregate], bool] | None = None,
) -> HandlerResult | None:
    """Load ``eval_id``, apply ``decide``, save and publish what it emitted.

    ``settled`` answers a lost race: whether the stored eval already is what
    this command was asked to make it. Omit it to let every conflict through.
    """
    aggregate = await repository.get_by_id(eval_id)
    if aggregate is None:
        return None
    try:
        decide(aggregate)
    except ValueError as e:
        return HandlerResult(success=False, error=str(e))

    events = aggregate.get_uncommitted_events()
    if not events:
        return HandlerResult(success=True)
    try:
        await repository.save(aggregate)
    except ConcurrencyConflictError:
        if settled is None:
            raise
        winner = await repository.get_by_id(eval_id)
        if winner is None or not settled(winner):
            raise
        return HandlerResult(success=True)
    if event_publisher is not None:
        await event_publisher.publish(events)
    aggregate.mark_events_as_committed()
    return HandlerResult(success=True)
