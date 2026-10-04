"""Whether an eval will take a run (evals plan, #967).

Three callers ask - a launch, a retroactive attach and a workflow's default -
and all three get the answer from the Eval AGGREGATE, loaded from its stream.
Never from a read model: the eval projection lags the store, so a projection
read could admit a run to an eval archived a moment ago, or refuse one created
a moment ago. Which eval a launch joins is ``eval_choice``'s question.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_sourcing import ConcurrencyConflictError

from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import (
    EvalId,
)
from syn_domain.contexts.orchestration.domain.commands.FreezeEvalCommand import (
    FreezeEvalCommand,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_eval.EvalAggregate import (
        EvalAggregate,
    )
    from syn_domain.repository import Repository


class EvalUnavailableError(ValueError):
    """The eval cannot take a run: it does not exist, or it is archived."""

    def __init__(self, eval_id: str, *, missing: bool) -> None:
        self.eval_id = eval_id
        self.missing = missing
        reason = "does not exist" if missing else "is archived"
        super().__init__(f"Eval {eval_id} {reason} and cannot take runs")


async def open_eval(repository: Repository[EvalAggregate], eval_id: str) -> EvalAggregate:
    """Load the eval from its stream and refuse one that cannot take runs."""
    aggregate = await repository.get_by_id(eval_id)
    if aggregate is None or aggregate.id is None:
        raise EvalUnavailableError(eval_id, missing=True)
    if aggregate.is_archived:
        raise EvalUnavailableError(eval_id, missing=False)
    return aggregate


async def admit_launch(repository: Repository[EvalAggregate], eval_id: str) -> None:
    """Admit a launch to the eval, freezing it first.

    A run admitted to an eval measures its goal against its baseline, so both
    are fixed before the first run starts (``EvalAggregate``'s ``frozen``).
    Idempotent: an eval already frozen records nothing, and a freeze that
    loses a race to another launch's freeze succeeds. A lost race to an
    archive refuses the launch.
    """
    aggregate = await open_eval(repository, eval_id)
    aggregate.freeze(FreezeEvalCommand(eval_id=EvalId.recorded(eval_id)))
    if not aggregate.get_uncommitted_events():
        return
    try:
        await repository.save(aggregate)
    except ConcurrencyConflictError:
        winner = await open_eval(repository, eval_id)
        if not winner.is_frozen:
            raise
        return
    aggregate.mark_events_as_committed()
