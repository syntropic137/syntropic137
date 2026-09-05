"""Persist the execution aggregate and keep this run's to-do list in step.

WHY THE PROCESSOR SHOULD NOT KNOW ANY OF THIS. The Processor To-Do List pattern
needs the to-do list to reflect a command the processor has only just issued,
and the subscription pipeline is eventually consistent - so the events are
applied to a process-local projection synchronously, right after the save. The
architecture notes call for exactly that; what they do not call for is the
processor knowing HOW. It knew four things: that the uncommitted events have to
be read off the aggregate before the save clears them, that a domain event
serialises by `model_dump`, `to_dict` or `vars` depending on what it is, that a
projection handler is named by lower-snake-casing the event type behind an
`on_` prefix, and that a missing handler is not an error. None of those is a
dispatch decision, and all four would have to change together the day the event
store or the projection base class changes.

A caller here says "this happened, keep my to-do list current" and finds out
nothing else. `open` is the first save of a run and `append` every save after
it; the difference is an expected-version rule the store enforces, not a
sequencing rule the caller applies.

WHAT THIS MODULE DELIBERATELY DOES NOT DO. It never decides that an event
happened. By the time `open` or `append` is called the aggregate has already
raised the events onto itself; this reads them, persists them, and projects
them. So `_apply` and `_raise_event` are the aggregate's words and are not
spelled here, even for a private helper with an unrelated job - the events
travel one way, into a read model, and the name has to say so. A helper here
called `_apply` was the whole of PR #1222's CI failure: `test_event_ownership`
matches those two names anywhere outside `aggregate_*/` and cannot see that the
receiver was a journal rather than an aggregate. Keeping the vocabulary
reserved is cheaper than teaching the checker about receivers, and it keeps a
grep for `_raise_event` answering the question people actually ask of it.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        ExecutionRepository,
        TodoProjection,
    )


class ExecutionJournal:
    """The execution's event stream, and the to-do list derived from it locally."""

    def __init__(self, repository: ExecutionRepository, projection: TodoProjection) -> None:
        self._repository = repository
        self._projection = projection

    async def open(self, aggregate: WorkflowExecutionAggregate) -> None:
        """Record the first events of a run, on a stream that must not already exist.

        Uses `save_new` (ExpectedVersion.NoStream) so a re-dispatch of the same
        execution id cannot quietly start a second run against the same stream.

        Raises:
            StreamAlreadyExistsError: the execution has already been started.
        """
        uncommitted = self._pending(aggregate)
        await self._repository.save_new(aggregate)
        await self._project(uncommitted)

    async def append(self, aggregate: WorkflowExecutionAggregate) -> None:
        """Record whatever the aggregate has decided since it was last saved."""
        uncommitted = self._pending(aggregate)
        await self._repository.save(aggregate)
        await self._project(uncommitted)

    @staticmethod
    def _pending(aggregate: WorkflowExecutionAggregate) -> list[object]:
        """The events the aggregate is about to commit, read before the save clears them."""
        return [envelope.event for envelope in aggregate.get_uncommitted_events()]

    async def _project(self, events: Sequence[object]) -> None:
        """Feed just-saved events to the local projection, in order.

        A projection with no handler for an event type is not a failure: the
        to-do list reacts to a handful of lifecycle events and ignores the
        rest, and requiring a handler per event would make every new event a
        breaking change to every projection.
        """
        for event in events:
            event_type = getattr(event, "event_type", type(event).__name__)
            event_data = self._serialize_event(event)
            handler = getattr(self._projection, self._event_type_to_handler(event_type), None)
            if handler:
                await handler(event_data)

    @staticmethod
    def _serialize_event(event: object) -> dict[str, Any]:
        """Serialize a domain event to a dict for projection handlers."""
        if hasattr(event, "model_dump"):
            return event.model_dump()  # type: ignore[union-attr]
        if hasattr(event, "to_dict"):
            return event.to_dict()  # type: ignore[union-attr]
        return vars(event)

    @staticmethod
    def _event_type_to_handler(event_type: str) -> str:
        """Convert CamelCase event type to on_snake_case handler name."""
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", event_type).lower()
        return f"on_{snake}"
