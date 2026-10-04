"""AddExecutionTags command (#967)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.orchestration._shared.tags import TagSet  # noqa: TC001


@command("AddExecutionTags", "Adds tags to a workflow execution")
class AddExecutionTagsCommand(BaseModel):
    """Add tags to an execution, retroactively.

    Changes the execution's current tags only. The tags it inherited at
    launch are a recorded fact and are never rewritten.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(..., min_length=1)
    tags: TagSet
