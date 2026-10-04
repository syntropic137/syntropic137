"""UpdateEval command handler (evals plan, #967).

A new baseline is pinned through ``RevisionResolverPort`` before the aggregate
sees it, all or nothing. The aggregate then decides: name and tags are always
editable, goal and baseline only until the eval is frozen, nothing once it is
archived. A baseline re-sent after its branch moved resolves to a new commit,
so on a frozen eval it is a change and is refused.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.eval_edit import edit_eval
from syn_domain.contexts.orchestration._shared.repository_baseline import resolve_baseline
from syn_domain.contexts.orchestration._shared.tags import TagSet
from syn_domain.contexts.orchestration.domain import HandlerResult
from syn_domain.contexts.orchestration.domain.commands.UpdateEvalCommand import (
    UpdateEvalCommand,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from syn_domain.contexts.orchestration._shared.repository_baseline import BaselineRequest
    from syn_domain.contexts.orchestration._shared.tag_edit import EventPublisher
    from syn_domain.contexts.orchestration.domain.aggregate_eval.EvalAggregate import (
        EvalAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import (
        EvalId,
        Goal,
    )
    from syn_domain.contexts.orchestration.ports.RevisionResolverPort import (
        RevisionResolverPort,
    )
    from syn_domain.repository import Repository


class UpdateEvalHandler:
    """Handler for the update-eval slice."""

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
        name: str | None = None,
        goal: Goal | None = None,
        baseline: Iterable[BaselineRequest] | None = None,
        add_tags: Iterable[str] = (),
        remove_tags: Iterable[str] = (),
    ) -> HandlerResult | None:
        """Apply the edit. ``None`` if the eval does not exist."""
        try:
            pinned = None if baseline is None else await resolve_baseline(self._resolver, baseline)
            command = UpdateEvalCommand(
                eval_id=eval_id,
                name=name,
                goal=goal,
                baseline_repos=pinned,
                add_tags=TagSet(add_tags),
                remove_tags=TagSet(remove_tags),
            )
        except ValueError as e:
            return HandlerResult(success=False, error=str(e))
        return await edit_eval(
            self._repository,
            command.aggregate_id,
            lambda aggregate: aggregate.update(command),
            self._event_publisher,
        )
