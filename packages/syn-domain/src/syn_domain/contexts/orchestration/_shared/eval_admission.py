"""Which eval a run belongs to, and whether that eval will take it (evals plan, #967).

Three callers ask the second question - a launch, a retroactive attach and a
workflow's default - and all three get the answer from the Eval AGGREGATE,
loaded from its stream. Never from a read model: the eval projection lags the
store, so a projection read could admit a run to an eval archived a moment
ago, or refuse one created a moment ago.

The first question is answered at dispatch, once, in this order:

1. an eval the launch names explicitly;
2. otherwise the workflow's ``default_eval_id``;
3. unless the launch asks for an ordinary run, which suppresses the default.

The answer is recorded on the execution's start event, so changing a workflow's
default later never reclassifies a run that already started.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Self

from event_sourcing import ConcurrencyConflictError
from pydantic import BaseModel, ConfigDict, model_validator

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


class EvalSelection(StrEnum):
    """How a launch arrived at its eval. Recorded on the start event."""

    EXPLICIT = "explicit"
    """The launch named the eval."""
    WORKFLOW_DEFAULT = "workflow_default"
    """The launch named none and the workflow had a default."""
    ORDINARY = "ordinary"
    """The launch asked for an ordinary run, suppressing any default."""
    NONE = "none"
    """The launch named none and the workflow had no default."""


class EvalChoice(BaseModel):
    """What a launch request says about evals. The empty choice defers to the workflow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    eval_id: EvalId | None = None
    ordinary: bool = False

    @model_validator(mode="after")
    def _one_or_the_other(self) -> Self:
        if self.ordinary and self.eval_id is not None:
            msg = "a launch cannot name an eval and ask for an ordinary run"
            raise ValueError(msg)
        return self

    def resolve(self, workflow_default: str | None) -> LaunchEval:
        """The eval this launch joins, given the workflow's default at dispatch."""
        if self.eval_id is not None:
            return LaunchEval(str(self.eval_id), EvalSelection.EXPLICIT)
        if self.ordinary:
            return LaunchEval(None, EvalSelection.ORDINARY)
        if workflow_default:
            return LaunchEval(workflow_default, EvalSelection.WORKFLOW_DEFAULT)
        return LaunchEval(None, EvalSelection.NONE)


@dataclass(frozen=True)
class LaunchEval:
    """A resolved launch: the eval joined (or None) and how it was chosen."""

    eval_id: str | None
    selection: EvalSelection


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
