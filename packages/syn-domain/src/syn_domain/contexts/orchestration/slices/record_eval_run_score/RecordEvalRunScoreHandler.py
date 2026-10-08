"""RecordEvalRunScore handler (Evals v2) - thin application service adapter.

Two streams, the same shape as an attach: the run's stream says whether it is a
member, the Eval's stream records the score. Membership is read from the
EXECUTION AGGREGATE, never the execution list, which lags the store.

There is no shared transaction. A detach that commits between the read and the
write leaves a score on a run that has just left the eval; the read side only
shows scores of current members, so that score is invisible unless the run is
attached again, when it is still the scorer's last word on that run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.eval_edit import edit_eval
from syn_domain.contexts.orchestration.domain.aggregate_eval.errors import (
    EvalRunNotMemberError,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.tag_edit import EventPublisher
    from syn_domain.contexts.orchestration.domain import HandlerResult
    from syn_domain.contexts.orchestration.domain.aggregate_eval.EvalAggregate import (
        EvalAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.domain.commands.RecordEvalRunScoreCommand import (
        RecordEvalRunScoreCommand,
    )
    from syn_domain.repository import Repository


class RecordEvalRunScoreHandler:
    """Application service handler for RecordEvalRunScoreCommand."""

    def __init__(
        self,
        repository: Repository[EvalAggregate],
        execution_repository: Repository[WorkflowExecutionAggregate],
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._executions = execution_repository
        self._event_publisher = event_publisher

    async def handle(self, command: RecordEvalRunScoreCommand) -> HandlerResult | None:
        """Record the score. ``None`` if the eval does not exist.

        Raises ``EvalRunNotMemberError`` when the execution is unknown or is not
        currently a run of this eval.
        """
        eval_id = str(command.eval_id)
        execution = await self._executions.get_by_id(command.execution_id)
        if execution is None or execution.eval_membership.eval_id != eval_id:
            raise EvalRunNotMemberError(eval_id, command.execution_id)
        return await edit_eval(
            self._repository,
            eval_id,
            lambda aggregate: aggregate.record_run_score(command),
            self._event_publisher,
        )
