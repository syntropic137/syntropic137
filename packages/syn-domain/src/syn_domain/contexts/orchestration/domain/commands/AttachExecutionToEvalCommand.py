"""AttachExecutionToEval command (evals plan, #967)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import (  # noqa: TC001
    EvalId,
)


@command("AttachExecutionToEval", "Makes an execution a member of an eval")
class AttachExecutionToEvalCommand(BaseModel):
    """Attach an execution to an eval, in any status, terminal ones included.

    Changes classification only: it reruns nothing and never claims the run
    started from the eval's baseline. An execution belongs to at most one
    eval, so attaching one that belongs to another is refused until it is
    detached. Attaching it to the eval it is already in records nothing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(..., min_length=1)
    eval_id: EvalId
