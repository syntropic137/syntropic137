"""SetWorkflowDefaultEval command (evals plan, #967)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import (  # noqa: TC001
    EvalId,
)


@command("SetWorkflowDefaultEval", "Sets or clears the eval a workflow's runs join by default")
class SetWorkflowDefaultEvalCommand(BaseModel):
    """Set the eval a launch that names none joins, or clear it with ``None``.

    Affects launches AFTER this one only: a run's membership is decided at
    dispatch, so changing the default never reclassifies a run.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(..., min_length=1)
    eval_id: EvalId | None
