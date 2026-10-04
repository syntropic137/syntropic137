"""FreezeEval command handler (evals plan, #967).

Fix the goal and baseline. Idempotent: launch admission sends it before every run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.eval_edit import edit_eval
from syn_domain.contexts.orchestration.domain.commands.FreezeEvalCommand import (
    FreezeEvalCommand,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.tag_edit import EventPublisher
    from syn_domain.contexts.orchestration.domain import HandlerResult
    from syn_domain.contexts.orchestration.domain.aggregate_eval.EvalAggregate import (
        EvalAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import EvalId
    from syn_domain.repository import Repository


class FreezeEvalHandler:
    """Handler for the freeze-eval slice."""

    def __init__(
        self,
        repository: Repository[EvalAggregate],
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._event_publisher = event_publisher

    async def handle(self, *, eval_id: EvalId) -> HandlerResult | None:
        """Freeze the eval. ``None`` if it does not exist."""
        command = FreezeEvalCommand(eval_id=eval_id)
        return await edit_eval(
            self._repository,
            command.aggregate_id,
            lambda aggregate: aggregate.freeze(command),
            self._event_publisher,
        )
