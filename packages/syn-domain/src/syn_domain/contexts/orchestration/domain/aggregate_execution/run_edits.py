"""The edits a run takes after launch: its tags and its eval membership (#967).

Both are retroactive labels on a run that already exists, and neither touches
its lifecycle. What an edit changes is decided by `ExecutionTags` and
`EvalMembership`; the handlers here only check the run exists and apply what
comes back, and replay the events those value objects produce.

A mixin rather than a free function so the `@command_handler` and
`@event_sourcing_handler` registrations stay on `WorkflowExecutionAggregate`,
which finds them through `dir(cls)` exactly as it finds its own.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Protocol

from event_sourcing import command_handler, event_sourcing_handler

from syn_domain.contexts.orchestration.domain.aggregate_execution.replay import evt

if TYPE_CHECKING:
    from event_sourcing import DomainEvent

    from syn_domain.contexts.orchestration.domain.aggregate_execution.eval_membership import (
        EvalMembership,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.execution_tags import (
        ExecutionTags,
    )
    from syn_domain.contexts.orchestration.domain.commands.AddExecutionTagsCommand import (
        AddExecutionTagsCommand,
    )
    from syn_domain.contexts.orchestration.domain.commands.AttachExecutionToEvalCommand import (
        AttachExecutionToEvalCommand,
    )
    from syn_domain.contexts.orchestration.domain.commands.DetachExecutionFromEvalCommand import (
        DetachExecutionFromEvalCommand,
    )
    from syn_domain.contexts.orchestration.domain.commands.RemoveExecutionTagsCommand import (
        RemoveExecutionTagsCommand,
    )
    from syn_domain.contexts.orchestration.domain.events.ExecutionAttachedToEvalEvent import (
        ExecutionAttachedToEvalEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.ExecutionDetachedFromEvalEvent import (
        ExecutionDetachedFromEvalEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.ExecutionTagsAddedEvent import (
        ExecutionTagsAddedEvent,
    )
    from syn_domain.contexts.orchestration.domain.events.ExecutionTagsRemovedEvent import (
        ExecutionTagsRemovedEvent,
    )


class _Edit(Protocol):
    """A tag or eval edit, decided by its value object once the run's ids are known."""

    def __call__(self, *, execution_id: str, workflow_id: str) -> DomainEvent | None: ...


class RunEdits:
    """Tag and eval edits for `WorkflowExecutionAggregate`, which owns the state."""

    _workflow_id: str | None
    _tags: ExecutionTags
    _eval: EvalMembership

    if TYPE_CHECKING:
        # Provided by `AggregateRoot`, which follows this mixin in the MRO.
        @property
        def id(self) -> str | None: ...

        def _apply(self, event: DomainEvent) -> None: ...

    @command_handler("AddExecutionTagsCommand")
    def add_tags(self, command: AddExecutionTagsCommand) -> None:
        """Add tags to the current set. None new, no event."""
        self._apply_edit(partial(self._tags.add, command.tags))

    @command_handler("RemoveExecutionTagsCommand")
    def remove_tags(self, command: RemoveExecutionTagsCommand) -> None:
        """Remove tags from the current set. None present, no event."""
        self._apply_edit(partial(self._tags.remove, command.tags))

    @command_handler("AttachExecutionToEvalCommand")
    def attach_to_eval(self, command: AttachExecutionToEvalCommand) -> None:
        """Join an eval, in any status. Already a member, no event."""
        self._apply_edit(partial(self._eval.attach, str(command.eval_id)))

    @command_handler("DetachExecutionFromEvalCommand")
    def detach_from_eval(self, command: DetachExecutionFromEvalCommand) -> None:
        """Leave the eval. In none, no event; the launch record is kept."""
        self._apply_edit(partial(self._eval.detach, str(command.eval_id)))

    def _apply_edit(self, edit: _Edit) -> None:
        """Apply what a tag or eval edit decided on an existing run; None changed nothing."""
        if self.id is None:
            msg = "Execution does not exist"
            raise ValueError(msg)
        event = edit(execution_id=str(self.id), workflow_id=self._workflow_id or "")
        if event is not None:
            self._apply(event)

    @event_sourcing_handler("ExecutionTagsAdded")
    def on_execution_tags_added(self, event: ExecutionTagsAddedEvent) -> None:
        """Apply ExecutionTagsAddedEvent. The launch snapshot is untouched."""
        self._tags = self._tags.with_added(evt(event, "tags") or [])

    @event_sourcing_handler("ExecutionTagsRemoved")
    def on_execution_tags_removed(self, event: ExecutionTagsRemovedEvent) -> None:
        """Apply ExecutionTagsRemovedEvent. The launch snapshot is untouched."""
        self._tags = self._tags.with_removed(evt(event, "tags") or [])

    @event_sourcing_handler("ExecutionAttachedToEval")
    def on_attached_to_eval(self, event: ExecutionAttachedToEvalEvent) -> None:
        """Apply ExecutionAttachedToEvalEvent."""
        self._eval = self._eval.with_attached(evt(event, "eval_id"))

    @event_sourcing_handler("ExecutionDetachedFromEval")
    def on_detached_from_eval(self, _event: ExecutionDetachedFromEvalEvent) -> None:
        """Apply ExecutionDetachedFromEvalEvent. The launch record stays."""
        self._eval = self._eval.detached()
