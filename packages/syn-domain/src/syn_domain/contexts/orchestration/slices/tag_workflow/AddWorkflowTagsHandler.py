"""AddWorkflowTags handler (#967) - thin application service adapter.

Adds tags to a workflow template. Affects future runs only: an execution's tags
are a snapshot taken at launch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.tag_edit import (
    EventPublisher,
    TagEditResult,
    edit_tags,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.tags import TagSet
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )
    from syn_domain.contexts.orchestration.domain.commands.AddWorkflowTagsCommand import (
        AddWorkflowTagsCommand,
    )
    from syn_domain.repository import Repository


class AddWorkflowTagsHandler:
    """Application service handler for AddWorkflowTagsCommand."""

    def __init__(
        self,
        repository: Repository[WorkflowTemplateAggregate],
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._event_publisher = event_publisher

    async def handle(self, command: AddWorkflowTagsCommand) -> TagEditResult[TagSet] | None:
        """Return the workflow's tags after the edit, or None if it is unknown."""
        return await edit_tags(
            self._repository,
            command.aggregate_id,
            lambda workflow: workflow.add_tags(command),
            lambda workflow: workflow.tags,
            self._event_publisher,
        )
