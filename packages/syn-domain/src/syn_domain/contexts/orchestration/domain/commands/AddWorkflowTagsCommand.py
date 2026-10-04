"""AddWorkflowTags command (#967)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.orchestration._shared.tags import TagSet  # noqa: TC001


@command("AddWorkflowTags", "Adds tags to a workflow template")
class AddWorkflowTagsCommand(BaseModel):
    """Add tags to a workflow template.

    Affects executions launched AFTER this; an execution keeps the tags it
    inherited at launch.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(..., min_length=1)
    tags: TagSet
