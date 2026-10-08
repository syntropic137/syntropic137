"""A `WorkflowExecutionStarted` an execution read model cannot apply (#1696)."""

from __future__ import annotations


class UnappliableStartError(ValueError):
    """A start event that names no execution, so there is no row to write.

    A subscribed handler that returns without writing is read as SUCCESS by
    `AutoDispatchProjection` and checkpointed past, so the start would go
    missing with the read model reporting itself current. Raising instead
    makes the dispatch a FAILURE: the checkpoint is not saved for this event
    and the coordinator holds the projection on it. The starts lost in #1696
    were never delivered at all (#1708); this guards the other way to lose one.
    """

    def __init__(self, read_model: str) -> None:
        super().__init__(
            f"{read_model}: WorkflowExecutionStarted carries no execution_id, "
            "so it cannot be applied"
        )
        self.read_model = read_model
