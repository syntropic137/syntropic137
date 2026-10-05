"""CreateEval command (evals plan, #967)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.orchestration._shared.repository_baseline import (  # noqa: TC001
    RepositoryBaseline,
)
from syn_domain.contexts.orchestration._shared.tags import TagSet
from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import (  # noqa: TC001
    EvalId,
    EvalName,
    Goal,
)


@command("CreateEval", "Creates an eval: a goal measured from pinned repository commits")
class CreateEvalCommand(BaseModel):
    """Create an eval.

    ``baseline_repos`` are already resolved to full commit shas: the slice
    handler resolves them through ``RevisionResolverPort`` before this command
    exists, so the aggregate never needs git.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    eval_id: EvalId
    name: EvalName
    goal: Goal
    starting_workflow_id: str | None = Field(default=None, min_length=1)
    baseline_repos: tuple[RepositoryBaseline, ...] = ()
    tags: TagSet = Field(default_factory=TagSet)

    @property
    def aggregate_id(self) -> str:
        return str(self.eval_id)
