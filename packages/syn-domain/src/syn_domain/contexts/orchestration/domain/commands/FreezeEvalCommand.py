"""FreezeEval command (evals plan, #967)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict

from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import (  # noqa: TC001
    EvalId,
)


@command("FreezeEval", "Fixes an eval's goal and baseline before its first run is admitted")
class FreezeEvalCommand(BaseModel):
    """Freeze an eval's goal and baseline.

    Idempotent: launch admission sends it before every run, and only the first
    one records anything.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    eval_id: EvalId

    @property
    def aggregate_id(self) -> str:
        return str(self.eval_id)
