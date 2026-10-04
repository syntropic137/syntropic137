"""The one load-decide-save path behind UpdateEval, FreezeEval and ArchiveEval (#967).

Mirrors ``tag_edit.edit_tags``. The three slices differ only in which aggregate
method they call, so they share this to agree on the rest: an unknown eval is
``None``, a broken rule is a failed ``HandlerResult`` with nothing written, and
a command that changes nothing succeeds and writes nothing.

A stale write is NOT caught here. The repository saves at the version the
aggregate was loaded at, so an Update racing a Freeze loses with
``ConcurrencyConflictError``; that reaches the caller, which maps it to a
conflict the same way it does for every other aggregate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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
) -> HandlerResult | None:
    """Load ``eval_id``, apply ``decide``, save and publish what it emitted."""
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
    await repository.save(aggregate)
    if event_publisher is not None:
        await event_publisher.publish(events)
    aggregate.mark_events_as_committed()
    return HandlerResult(success=True)
