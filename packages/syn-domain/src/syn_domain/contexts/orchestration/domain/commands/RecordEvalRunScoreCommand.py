"""RecordEvalRunScore command (Evals v2)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import (  # noqa: TC001
    EvalId,
    Verdict,
)


@command("RecordEvalRunScore", "Records a scorer's verdict on one run of an eval")
class RecordEvalRunScoreCommand(BaseModel):
    """Score one run of an eval. A later score of the same run replaces it.

    Membership is NOT checked here: the run owns it, on its own stream. The
    slice handler reads it before this reaches the Eval aggregate.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    eval_id: EvalId
    execution_id: str = Field(min_length=1)
    verdict: Verdict
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    """Optional numeric score in [0, 1], beside the verdict, never instead of it."""
    evidence: str = ""
    """Markdown: why the scorer reached this verdict."""
    scorer: str = Field(min_length=1)
    scorer_version: str = Field(min_length=1)
    judge_model: str | None = Field(default=None, min_length=1)
    """The model that judged the run; None for a deterministic scorer (#1788)."""

    @property
    def aggregate_id(self) -> str:
        return str(self.eval_id)
