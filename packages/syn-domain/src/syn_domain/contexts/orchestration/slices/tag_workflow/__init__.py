"""Tag workflow slice (#967): add and remove a workflow template's tags."""

from syn_domain.contexts.orchestration.slices.tag_workflow.AddWorkflowTagsHandler import (
    AddWorkflowTagsHandler,
)
from syn_domain.contexts.orchestration.slices.tag_workflow.RemoveWorkflowTagsHandler import (
    RemoveWorkflowTagsHandler,
)

__all__ = ["AddWorkflowTagsHandler", "RemoveWorkflowTagsHandler"]
