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
    from syn_domain.contexts.orchestration._shared.eval_choice import EvalChoice, LaunchEval
    from syn_domain.contexts.orchestration._shared.repository_baseline import (
        RepositoryBaseline,
    )
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


async def admit_launch(
    repository: Repository[EvalAggregate], eval_id: str
) -> tuple[RepositoryBaseline, ...]:
    """Admit a launch to the eval, freezing it first, and return the frozen baseline.

    A run admitted to an eval measures its goal against its baseline, so both
    are fixed before the first run starts (``EvalAggregate``'s ``frozen``).
    Idempotent: an eval already frozen records nothing, and a freeze that
    loses a race to another launch's freeze succeeds. A lost race to an
    archive, or to a baseline edit, refuses the launch.

    The baseline returned is the one on the stream once the eval is frozen -
    the winner's, after a lost race - so the run records exactly what every
    other run of the eval starts from.
    """
    aggregate = await open_eval(repository, eval_id)
    aggregate.freeze(FreezeEvalCommand(eval_id=EvalId.recorded(eval_id)))
    if not aggregate.get_uncommitted_events():
        return aggregate.baseline_repos
    try:
        await repository.save(aggregate)
    except ConcurrencyConflictError:
        winner = await open_eval(repository, eval_id)
        if not winner.is_frozen:
            raise
        return winner.baseline_repos
    aggregate.mark_events_as_committed()
    return aggregate.baseline_repos


async def launch_eval_for(
    repository: Repository[EvalAggregate],
    choice: EvalChoice,
    workflow_default: str | None,
) -> LaunchEval:
    """The eval a launch joins, admitted, carrying the baseline every run of it checks out.

    Called ONCE, by whoever builds the ``ExecuteWorkflowCommand``, and the
    answer travels on the command. A retried dispatch of that command
    therefore joins the eval it was dispatched into, at the SHAs it was
    dispatched with, even if the workflow's default changed in between.
    Refuses (``EvalUnavailableError``) an eval that is missing or archived.
    """
    launch = choice.resolve(workflow_default)
    if launch.eval_id is None:
        return launch
    return launch.admitted(await admit_launch(repository, str(launch.eval_id)))
