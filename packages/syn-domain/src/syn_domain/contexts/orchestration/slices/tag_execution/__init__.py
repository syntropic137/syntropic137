"""Tag execution slice (#967): add and remove an execution's tags."""

from syn_domain.contexts.orchestration.slices.tag_execution.AddExecutionTagsHandler import (
    AddExecutionTagsHandler,
)
from syn_domain.contexts.orchestration.slices.tag_execution.RemoveExecutionTagsHandler import (
    RemoveExecutionTagsHandler,
)

__all__ = ["AddExecutionTagsHandler", "RemoveExecutionTagsHandler"]
