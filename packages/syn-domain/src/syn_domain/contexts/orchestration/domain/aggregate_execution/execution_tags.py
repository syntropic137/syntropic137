"""An execution's tags: what it launched with, and what it carries now (#967).

Two sets, because they answer different questions:

- ``inherited`` is the launch snapshot recorded on ``WorkflowExecutionStarted``:
  the workflow's tags at that moment united with the request's. It is a fact
  about the launch and is never rewritten.
- ``current`` starts equal to it and is what ``ExecutionTagsAdded`` and
  ``ExecutionTagsRemoved`` edit, retroactively. Removing an inherited tag from
  ``current`` is allowed; ``inherited`` still says the run launched with it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.tags import TagSet

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

    def newly_added(self, tags: TagSet) -> TagSet:
        """The tags adding ``tags`` would actually add. Raises over the limit."""
        return self.current.union(tags).difference(self.current)

    def actually_removed(self, tags: TagSet) -> TagSet:
        """The tags removing ``tags`` would actually remove."""
        return tags.intersection(self.current)

    def with_added(self, recorded: Iterable[str]) -> ExecutionTags:
        return ExecutionTags(self.inherited, TagSet.recorded([*self.current, *recorded]))

    def with_removed(self, recorded: Iterable[str]) -> ExecutionTags:
        return ExecutionTags(self.inherited, self.current.difference(TagSet.recorded(recorded)))
