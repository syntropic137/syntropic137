"""UpdateEval command (evals plan, #967)."""

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


@command("UpdateEval", "Renames, retags, or (before freezing) re-aims an eval")
class UpdateEvalCommand(BaseModel):
    """Change part of an eval. A field left ``None`` is left as it is.

    Tags are edited as additions and removals, never replaced wholesale, so
    two people tagging the same eval at once cannot erase each other's tags.
    ``goal`` and ``baseline_repos`` are refused once the eval is frozen,
    unless they equal what is already recorded.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    eval_id: EvalId
    name: EvalName | None = None
    goal: Goal | None = None
    baseline_repos: tuple[RepositoryBaseline, ...] | None = None
    add_tags: TagSet = Field(default_factory=TagSet)
    remove_tags: TagSet = Field(default_factory=TagSet)

    @property
    def aggregate_id(self) -> str:
        return str(self.eval_id)
