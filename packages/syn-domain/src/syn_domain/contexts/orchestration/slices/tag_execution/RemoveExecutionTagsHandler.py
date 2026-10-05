"""RemoveExecutionTags handler (#967) - thin application service adapter.

Removes tags from an execution, retroactively. Edits its current tags only; the tags
it inherited at launch are never rewritten.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.tag_edit import (
    EventPublisher,
    TagEditResult,
    edit_tags,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.execution_tags import (
        ExecutionTags,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.domain.commands.RemoveExecutionTagsCommand import (
        RemoveExecutionTagsCommand,
    )
    from syn_domain.repository import Repository


class RemoveExecutionTagsHandler:
    """Application service handler for RemoveExecutionTagsCommand."""

    def __init__(
        self,
        repository: Repository[WorkflowExecutionAggregate],
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._event_publisher = event_publisher

    async def handle(
        self, command: RemoveExecutionTagsCommand
    ) -> TagEditResult[ExecutionTags] | None:
        """Return the execution's tags after the edit, or None if it is unknown."""
        return await edit_tags(
            self._repository,
            command.aggregate_id,
            lambda execution: execution.remove_tags(command),
            lambda execution: execution.tags,
            self._event_publisher,
        )
