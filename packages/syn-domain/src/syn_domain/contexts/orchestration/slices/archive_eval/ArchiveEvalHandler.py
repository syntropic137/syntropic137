"""ArchiveEval command handler (evals plan, #967).

Retire the eval. Idempotent; a frozen eval can be archived.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.eval_edit import edit_eval
from syn_domain.contexts.orchestration.domain.commands.ArchiveEvalCommand import (
    ArchiveEvalCommand,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.tag_edit import EventPublisher
    from syn_domain.contexts.orchestration.domain import HandlerResult
    from syn_domain.contexts.orchestration.domain.aggregate_eval.EvalAggregate import (
        EvalAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import EvalId
    from syn_domain.repository import Repository


class ArchiveEvalHandler:
    """Handler for the archive-eval slice."""

    def __init__(
        self,
        repository: Repository[EvalAggregate],
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._event_publisher = event_publisher

    async def handle(self, *, eval_id: EvalId, archived_by: str = "") -> HandlerResult | None:
        """Archive the eval. ``None`` if it does not exist."""
        command = ArchiveEvalCommand(eval_id=eval_id, archived_by=archived_by)
        return await edit_eval(
            self._repository,
            command.aggregate_id,
            lambda aggregate: aggregate.archive(command),
            self._event_publisher,
        )
