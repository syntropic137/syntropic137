"""CreateEval command handler (evals plan, #967).

Steps, mirroring ``RegisterSkillHandler``:

1. Pin every requested baseline ref to a full commit sha through
   ``RevisionResolverPort``. One unresolved ref refuses the whole create and
   records nothing.
2. Idempotency: if the eval already exists and this request is the one that
   created it, succeed without writing. A different request for a taken id
   fails with ``EvalAlreadyExistsError``.
3. ``save_new`` writes at "no stream yet". If a concurrent create beat us,
   ``StreamAlreadyExistsError`` is answered exactly like step 2, against the
   winner.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from event_sourcing import StreamAlreadyExistsError

from syn_domain.contexts.orchestration._shared.repository_baseline import resolve_baseline
from syn_domain.contexts.orchestration._shared.tags import TagSet
from syn_domain.contexts.orchestration.domain import HandlerResult
from syn_domain.contexts.orchestration.domain.aggregate_eval.errors import (
    EvalAlreadyExistsError,
)
from syn_domain.contexts.orchestration.domain.aggregate_eval.EvalAggregate import (
    EvalAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.CreateEvalCommand import (
    CreateEvalCommand,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from syn_domain.contexts.orchestration._shared.repository_baseline import BaselineRequest
    from syn_domain.contexts.orchestration._shared.tag_edit import EventPublisher
    from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import (
        EvalId,
        Goal,
    )
    from syn_domain.contexts.orchestration.ports.RevisionResolverPort import (
        RevisionResolverPort,
    )
    from syn_domain.repository import Repository

logger = logging.getLogger(__name__)


class CreateEvalHandler:
    """Handler for the create-eval slice."""

    def __init__(
        self,
        repository: Repository[EvalAggregate],
        resolver: RevisionResolverPort,
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._resolver = resolver
        self._event_publisher = event_publisher

    async def handle(
        self,
        *,
        eval_id: EvalId,
        name: str,
        goal: Goal,
        baseline: Iterable[BaselineRequest] = (),
        tags: Iterable[str] = (),
        starting_workflow_id: str | None = None,
    ) -> HandlerResult:
        """Create ``eval_id``, or confirm an identical earlier create."""
        try:
            command = CreateEvalCommand(
                eval_id=eval_id,
                name=name,
                goal=goal,
                starting_workflow_id=starting_workflow_id,
                baseline_repos=await resolve_baseline(self._resolver, baseline),
                tags=TagSet(tags),
            )
        except ValueError as e:
            return HandlerResult(success=False, error=str(e))

        existing = await self._repository.get_by_id(command.aggregate_id)
        if existing is not None:
            return _retry_or_conflict(existing, command)

        aggregate = EvalAggregate()
        try:
            aggregate.create(command)
        except ValueError as e:
            return HandlerResult(success=False, error=str(e))
        events = aggregate.get_uncommitted_events()

        try:
            await self._repository.save_new(aggregate)
        except StreamAlreadyExistsError:
            logger.info("Concurrent eval create collision", extra={"eval_id": str(eval_id)})
            winner = await self._repository.get_by_id(command.aggregate_id)
            if winner is None:
                msg = f"StreamAlreadyExistsError for eval {eval_id} but it cannot be loaded"
                raise RuntimeError(msg) from None
            return _retry_or_conflict(winner, command)

        if self._event_publisher is not None:
            await self._event_publisher.publish(events)
        aggregate.mark_events_as_committed()
        return HandlerResult(success=True)


def _retry_or_conflict(existing: EvalAggregate, command: CreateEvalCommand) -> HandlerResult:
    if existing.was_created_by(command):
        return HandlerResult(success=True)
    return HandlerResult(success=False, error=str(EvalAlreadyExistsError(command.aggregate_id)))
