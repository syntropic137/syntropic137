"""The shape of a tag or eval-membership edit on a workflow execution.

Kept beside the aggregate so `WorkflowExecutionAggregate` stays under the
max-loc-file budget; the aggregate applies these in `_apply_edit`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from event_sourcing import DomainEvent


class AggregateEdit(Protocol):
    """A tag or eval edit, decided by its value object once the run's ids are known."""

    def __call__(self, *, execution_id: str, workflow_id: str) -> DomainEvent | None: ...
