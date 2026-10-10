"""ArchiveEval command (evals plan, #967)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict

from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import (  # noqa: TC001
    EvalId,
)


@command("ArchiveEval", "Retires an eval: it stays readable but admits no new runs")
class ArchiveEvalCommand(BaseModel):
    """Archive an eval. Idempotent: archiving an archived eval records nothing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    eval_id: EvalId
    archived_by: str = ""

    @property
    def aggregate_id(self) -> str:
        return str(self.eval_id)
