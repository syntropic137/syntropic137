"""The one load-decide-save path behind attaching and detaching a run (#967).

Mirrors ``eval_edit.edit_eval``, on the execution's stream instead of the eval's:
an unknown execution is ``None``, a broken rule is a failed result with nothing
written, and a command that changes nothing succeeds and writes nothing.

Both commands are idempotent, so a lost race is settled the way a FreezeEval's
is: reload, and if the stored run already is what this command was asked to
make it, succeed having written nothing. Anything else is still a conflict.

``admit`` runs only when the command would write. A command that changes
nothing never asks it, so repeating an attach to an eval archived since is
still the no-op it was (Codex review, PR #1562).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from event_sourcing import ConcurrencyConflictError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from syn_domain.contexts.orchestration._shared.tag_edit import EventPublisher
    from syn_domain.contexts.orchestration.domain.aggregate_execution.eval_membership import (
        EvalMembership,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.repository import Repository


@dataclass(frozen=True)
class EvalMembershipResult:
    """The outcome of an attach or detach.

    ``membership`` is the run's membership after the edit, set on success only.
    ``error`` names the broken rule on failure.
    """

    success: bool
    error: str = ""
    membership: EvalMembership | None = None


async def edit_membership(
    repository: Repository[WorkflowExecutionAggregate],
    execution_id: str,
    decide: Callable[[WorkflowExecutionAggregate], None],
    settled: Callable[[EvalMembership], bool],
    event_publisher: EventPublisher | None = None,
    admit: Callable[[], Awaitable[None]] | None = None,
) -> EvalMembershipResult | None:
    """Load the run, apply ``decide``, ``admit``, save and publish. ``None`` if it is unknown.

    ``admit`` may raise to refuse the write; it is not asked when nothing changes.
    """
    aggregate = await repository.get_by_id(execution_id)
    if aggregate is None:
        return None
    try:
        decide(aggregate)
    except ValueError as e:
        return EvalMembershipResult(success=False, error=str(e))
    events = aggregate.get_uncommitted_events()
    if not events:
        return EvalMembershipResult(success=True, membership=aggregate.eval_membership)
    if admit is not None:
        await admit()
    try:
        await repository.save(aggregate)
    except ConcurrencyConflictError:
        winner = await repository.get_by_id(execution_id)
        if winner is None or not settled(winner.eval_membership):
            raise
        return EvalMembershipResult(success=True, membership=winner.eval_membership)
    if event_publisher is not None:
        await event_publisher.publish(events)
    aggregate.mark_events_as_committed()
    return EvalMembershipResult(success=True, membership=aggregate.eval_membership)
