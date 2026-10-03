"""An execution's tags: what it launched with, and what it carries now (#967).

Two sets, because they answer different questions:

- ``inherited`` is the launch snapshot recorded on ``WorkflowExecutionStarted``:
  the workflow's tags at that moment united with the request's. It is a fact
  about the launch and is never rewritten.
- ``current`` starts equal to it and is what ``ExecutionTagsAdded`` and
  ``ExecutionTagsRemoved`` edit, retroactively. Removing an inherited tag from
  ``current`` is allowed; ``inherited`` still says the run launched with it.

What an add or a remove would change is decided here too, so the aggregate's
command handlers only check the execution exists and apply what comes back.
An edit that changes nothing records nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.tags import TagSet
from syn_domain.contexts.orchestration.domain.events.ExecutionTagsAddedEvent import (
    ExecutionTagsAddedEvent,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionTagsRemovedEvent import (
    ExecutionTagsRemovedEvent,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True)
class ExecutionTags:
    inherited: TagSet = field(default_factory=TagSet)
    current: TagSet = field(default_factory=TagSet)

    @classmethod
    def launched_with(cls, recorded: Iterable[str]) -> ExecutionTags:
        tags = TagSet.recorded(recorded)
        return cls(inherited=tags, current=tags)

    def add(
        self, tags: TagSet, *, execution_id: str, workflow_id: str
    ) -> ExecutionTagsAddedEvent | None:
        """The event adding ``tags`` records, or None when none are new.

        Raises when ``tags`` is empty or the result would exceed the limit.
        """
        added = self.current.union(_requested(tags)).difference(self.current)
        if not added:
            return None
        return ExecutionTagsAddedEvent(
            execution_id=execution_id, workflow_id=workflow_id, tags=list(added)
        )

    def remove(
        self, tags: TagSet, *, execution_id: str, workflow_id: str
    ) -> ExecutionTagsRemovedEvent | None:
        """The event removing ``tags`` records, or None when none are present.

        Raises when ``tags`` is empty.
        """
        removed = _requested(tags).intersection(self.current)
        if not removed:
            return None
        return ExecutionTagsRemovedEvent(
            execution_id=execution_id, workflow_id=workflow_id, tags=list(removed)
        )

    def with_added(self, recorded: Iterable[str]) -> ExecutionTags:
        return ExecutionTags(self.inherited, TagSet.recorded([*self.current, *recorded]))

    def with_removed(self, recorded: Iterable[str]) -> ExecutionTags:
        return ExecutionTags(self.inherited, self.current.difference(TagSet.recorded(recorded)))


def _requested(tags: TagSet) -> TagSet:
    """An edit names at least one tag; an empty one is a caller's mistake."""
    if not tags:
        msg = "At least one tag is required"
        raise ValueError(msg)
    return tags
