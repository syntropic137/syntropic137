"""SetWorkflowDefaultEval handler (evals plan, #967) - thin application service adapter.

Sets the eval a workflow's runs join when the launch names none, or clears it.
Setting one requires the eval to exist and not be archived, decided by loading
the Eval aggregate. Clearing one never consults an eval.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.eval_admission import open_eval
from syn_domain.contexts.orchestration.domain import HandlerResult

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.tag_edit import EventPublisher
    from syn_domain.contexts.orchestration.domain.aggregate_eval.EvalAggregate import (
        EvalAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )
    from syn_domain.contexts.orchestration.domain.commands.SetWorkflowDefaultEvalCommand import (
        SetWorkflowDefaultEvalCommand,
    )
    from syn_domain.repository import Repository


class SetWorkflowDefaultEvalHandler:
    """Application service handler for SetWorkflowDefaultEvalCommand."""

    def __init__(
        self,
        repository: Repository[WorkflowTemplateAggregate],
        eval_repository: Repository[EvalAggregate],
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._eval_repository = eval_repository
        self._event_publisher = event_publisher

    async def handle(self, command: SetWorkflowDefaultEvalCommand) -> HandlerResult | None:
        """Set or clear the default. ``None`` if the workflow is unknown.

        Raises ``EvalUnavailableError`` if the eval does not exist or is archived.
        """
        workflow = await self._repository.get_by_id(command.aggregate_id)
        if workflow is None:
            return None
        if command.eval_id is not None:
            await open_eval(self._eval_repository, str(command.eval_id))
        try:
            workflow.set_default_eval(command)
        except ValueError as e:
            return HandlerResult(success=False, error=str(e))
        events = workflow.get_uncommitted_events()
        if events:
            await self._repository.save(workflow)
            if self._event_publisher is not None:
                await self._event_publisher.publish(events)
            workflow.mark_events_as_committed()
        return HandlerResult(success=True)
