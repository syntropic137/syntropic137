"""DetachExecutionFromEval handler (evals plan, #967) - thin application service adapter.

Takes a run out of the eval it belongs to. The eval is not consulted: a run can
leave an archived eval. What the run was launched into is kept on its start
event, so a detach never rewrites history.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.eval_membership_edit import (
    EvalMembershipResult,
    edit_membership,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.tag_edit import EventPublisher
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.domain.commands.DetachExecutionFromEvalCommand import (
        DetachExecutionFromEvalCommand,
    )
    from syn_domain.repository import Repository


class DetachExecutionFromEvalHandler:
    """Application service handler for DetachExecutionFromEvalCommand."""

    def __init__(
        self,
        repository: Repository[WorkflowExecutionAggregate],
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._event_publisher = event_publisher

    async def handle(self, command: DetachExecutionFromEvalCommand) -> EvalMembershipResult | None:
        """Return the run's membership after the detach, or None if the run is unknown."""
        return await edit_membership(
            self._repository,
            command.aggregate_id,
            lambda execution: execution.detach_from_eval(command),
            lambda stored: stored.eval_id is None,
            self._event_publisher,
        )
