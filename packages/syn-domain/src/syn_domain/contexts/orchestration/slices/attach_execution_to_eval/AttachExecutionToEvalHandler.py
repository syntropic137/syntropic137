"""AttachExecutionToEval handler (evals plan, #967) - thin application service adapter.

Makes a run a member of an eval, in any status: a run that finished last week
can be attached today. It changes classification only. Nothing is rerun, and
the eval's baseline is not copied into the run, which never started from it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.eval_admission import open_eval
from syn_domain.contexts.orchestration._shared.eval_membership_edit import (
    EvalMembershipResult,
    edit_membership,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.tag_edit import EventPublisher
    from syn_domain.contexts.orchestration.domain.aggregate_eval.EvalAggregate import (
        EvalAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.domain.commands.AttachExecutionToEvalCommand import (
        AttachExecutionToEvalCommand,
    )
    from syn_domain.repository import Repository


class AttachExecutionToEvalHandler:
    """Application service handler for AttachExecutionToEvalCommand."""

    def __init__(
        self,
        repository: Repository[WorkflowExecutionAggregate],
        eval_repository: Repository[EvalAggregate],
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._eval_repository = eval_repository
        self._event_publisher = event_publisher

    async def handle(self, command: AttachExecutionToEvalCommand) -> EvalMembershipResult | None:
        """Return the run's membership after the attach, or None if the run is unknown.

        Raises ``EvalUnavailableError`` if the eval does not exist or is archived,
        decided by loading the Eval aggregate and never by a read model.
        """
        eval_id = str(command.eval_id)
        await open_eval(self._eval_repository, eval_id)
        return await edit_membership(
            self._repository,
            command.aggregate_id,
            lambda execution: execution.attach_to_eval(command),
            lambda stored: stored.eval_id == eval_id,
            self._event_publisher,
        )
