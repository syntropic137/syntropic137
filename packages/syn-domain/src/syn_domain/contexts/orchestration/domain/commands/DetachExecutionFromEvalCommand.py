"""DetachExecutionFromEval command (evals plan, #967)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import (  # noqa: TC001
    EvalId,
)


@command("DetachExecutionFromEval", "Ends an execution's membership of an eval")
class DetachExecutionFromEvalCommand(BaseModel):
    """Detach an execution from the eval it belongs to.

    ``eval_id`` names the eval the caller believes the run is in, so a detach
    aimed at the wrong eval is refused instead of detaching another one. A run
    in no eval records nothing. The launch record is never rewritten: the start
    event still says which eval, if any, the run was launched into.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(..., min_length=1)
    eval_id: EvalId
